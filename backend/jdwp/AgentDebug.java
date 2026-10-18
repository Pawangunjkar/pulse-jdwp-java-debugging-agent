package com.pulse.jdwp;

import com.sun.jdi.AbsentInformationException;
import com.sun.jdi.Bootstrap;
import com.sun.jdi.LocalVariable;
import com.sun.jdi.Location;
import com.sun.jdi.ReferenceType;
import com.sun.jdi.StackFrame;
import com.sun.jdi.ThreadReference;
import com.sun.jdi.Value;
import com.sun.jdi.VirtualMachine;
import com.sun.jdi.connect.AttachingConnector;
import com.sun.jdi.connect.Connector;
import com.sun.jdi.event.BreakpointEvent;
import com.sun.jdi.event.ClassPrepareEvent;
import com.sun.jdi.event.Event;
import com.sun.jdi.event.EventSet;
import com.sun.jdi.event.ExceptionEvent;
import com.sun.jdi.event.StepEvent;
import com.sun.jdi.request.BreakpointRequest;
import com.sun.jdi.request.ClassPrepareRequest;
import com.sun.jdi.request.EventRequest;
import com.sun.jdi.request.EventRequestManager;
import com.sun.jdi.request.ExceptionRequest;
import com.sun.jdi.request.StepRequest;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * Long-lived JDWP session. One JSON object per line on stdout.
 * Stdin commands: break, catch, wait, step, next, cont, locals, where, threads, print, exit.
 * Every command ends with {"event":"ready"}.
 */
public class AgentDebug {
    private static VirtualMachine vm;
    private static ThreadReference suspendedThread;

    public static void main(String[] args) throws Exception {
        String host = arg(args, "--host", "127.0.0.1");
        String port = arg(args, "--port", "5005");
        try {
            vm = attach(host, port);
            emit("{\"event\":\"attach\",\"command\":\"jdi attach " + esc(host) + ":" + esc(port) + "\",\"output\":\"" + esc(threadList(vm)) + "\"}");
        } catch (Exception ex) {
            emit("{\"event\":\"error\",\"detail\":\"" + esc(ex.toString()) + "\"}");
            emit("{\"event\":\"ready\"}");
            return;
        }
        emit("{\"event\":\"ready\"}");
        BufferedReader reader = new BufferedReader(new InputStreamReader(System.in, "UTF-8"));
        String line;
        while ((line = reader.readLine()) != null) {
            String command = line.trim();
            if (command.length() == 0) {
                emit("{\"event\":\"ready\"}");
                continue;
            }
            try {
                dispatch(command);
            } catch (Exception ex) {
                emit("{\"event\":\"error\",\"detail\":\"" + esc(ex.toString()) + "\"}");
            }
            emit("{\"event\":\"ready\"}");
            if ("exit".equals(command)) {
                break;
            }
        }
        detach();
    }

    private static void dispatch(String command) throws Exception {
        if (command.startsWith("break ")) {
            doBreak(command.substring(6).trim());
        } else if (command.startsWith("catch ")) {
            doCatch(command.substring(6).trim());
        } else if (command.startsWith("wait")) {
            String rest = command.length() > 4 ? command.substring(4).trim() : "8";
            doWait(Long.parseLong(rest.length() == 0 ? "8" : rest));
        } else if ("step".equals(command)) {
            doStep(StepRequest.STEP_INTO);
        } else if ("next".equals(command)) {
            doStep(StepRequest.STEP_OVER);
        } else if ("cont".equals(command)) {
            vm.resume();
            suspendedThread = null;
            emit("{\"event\":\"cont\",\"command\":\"cont\",\"output\":\"resumed\"}");
        } else if ("locals".equals(command)) {
            reportCurrent("locals");
        } else if ("where".equals(command)) {
            reportCurrent("where");
        } else if ("threads".equals(command)) {
            emit("{\"event\":\"threads\",\"command\":\"threads\",\"output\":\"" + esc(threadList(vm)) + "\"}");
        } else if (command.startsWith("print ")) {
            doPrint(command.substring(6).trim());
        } else if ("exit".equals(command)) {
            emit("{\"event\":\"detach\",\"command\":\"exit\",\"output\":\"detached\"}");
        } else {
            emit("{\"event\":\"error\",\"detail\":\"Unknown command " + esc(command) + "\"}");
        }
    }

    private static void doBreak(String spec) throws Exception {
        int colon = spec.lastIndexOf(':');
        if (colon < 1) {
            emit("{\"event\":\"error\",\"detail\":\"break expects Class:line\"}");
            return;
        }
        String className = spec.substring(0, colon);
        int line = Integer.parseInt(spec.substring(colon + 1));
        List<ReferenceType> types = vm.classesByName(className);
        if (types.isEmpty()) {
            types = waitForClass(className);
        }
        int armed = 0;
        for (ReferenceType type : types) {
            for (Location location : lineLocations(type, line)) {
                BreakpointRequest request = vm.eventRequestManager().createBreakpointRequest(location);
                request.setSuspendPolicy(EventRequest.SUSPEND_EVENT_THREAD);
                request.enable();
                armed++;
            }
        }
        emit("{\"event\":\"breakpoint\",\"command\":\"stop at " + esc(className) + ":" + line + "\",\"output\":\"armed=" + armed + "\"}");
        if (armed == 0) {
            emit("{\"event\":\"error\",\"detail\":\"No executable location at " + esc(className) + ":" + line + "\"}");
        }
    }

    private static List<ReferenceType> waitForClass(String className) throws Exception {
        EventRequestManager manager = vm.eventRequestManager();
        ClassPrepareRequest prepare = manager.createClassPrepareRequest();
        prepare.addClassFilter(className);
        prepare.setSuspendPolicy(EventRequest.SUSPEND_ALL);
        prepare.enable();
        emit("{\"event\":\"class_prepare\",\"command\":\"await " + esc(className) + "\",\"output\":\"class not loaded yet\"}");
        vm.resume();
        EventSet set = poll(15000);
        prepare.disable();
        List<ReferenceType> types = new ArrayList<ReferenceType>();
        if (set == null) {
            emit("{\"event\":\"error\",\"detail\":\"Timed out waiting for " + esc(className) + " to load\"}");
            return types;
        }
        for (Event event : set) {
            if (event instanceof ClassPrepareEvent) {
                types.add(((ClassPrepareEvent) event).referenceType());
            }
        }
        return types;
    }

    private static void doCatch(String exception) {
        List<ReferenceType> types = vm.classesByName(exception);
        ReferenceType type = types.isEmpty() ? null : types.get(0);
        ExceptionRequest request = vm.eventRequestManager().createExceptionRequest(type, true, true);
        request.setSuspendPolicy(EventRequest.SUSPEND_EVENT_THREAD);
        request.addClassFilter("com.*");
        request.enable();
        emit("{\"event\":\"catch\",\"command\":\"catch " + esc(exception) + "\",\"output\":\"armed\"}");
    }

    private static void doWait(long seconds) throws Exception {
        vm.resume();
        long deadline = System.currentTimeMillis() + seconds * 1000L;
        while (System.currentTimeMillis() < deadline) {
            EventSet set = vm.eventQueue().remove(400);
            if (set == null) {
                continue;
            }
            for (Event event : set) {
                if (event instanceof BreakpointEvent) {
                    BreakpointEvent hit = (BreakpointEvent) event;
                    suspendedThread = hit.thread();
                    report(hit.thread(), hit.location(), "breakpoint");
                    return;
                }
                if (event instanceof ExceptionEvent) {
                    ExceptionEvent hit = (ExceptionEvent) event;
                    suspendedThread = hit.thread();
                    report(hit.thread(), hit.location(), "exception");
                    return;
                }
            }
            set.resume();
        }
        emit("{\"event\":\"error\",\"detail\":\"Timed out waiting for a breakpoint or exception\"}");
    }

    private static void doStep(int depth) throws Exception {
        if (suspendedThread == null || !suspendedThread.isSuspended()) {
            emit("{\"event\":\"error\",\"detail\":\"No suspended thread to step\"}");
            return;
        }
        EventRequestManager manager = vm.eventRequestManager();
        for (StepRequest existing : manager.stepRequests()) {
            manager.deleteEventRequest(existing);
        }
        StepRequest request = manager.createStepRequest(suspendedThread, StepRequest.STEP_LINE, depth);
        request.setSuspendPolicy(EventRequest.SUSPEND_EVENT_THREAD);
        request.addCountFilter(1);
        request.enable();
        suspendedThread.resume();
        EventSet set = poll(8000);
        request.disable();
        if (set == null) {
            emit("{\"event\":\"error\",\"detail\":\"Timed out while stepping\"}");
            return;
        }
        for (Event event : set) {
            if (event instanceof StepEvent) {
                StepEvent step = (StepEvent) event;
                suspendedThread = step.thread();
                report(step.thread(), step.location(), depth == StepRequest.STEP_OVER ? "next" : "step");
                return;
            }
        }
        set.resume();
    }

    private static void doPrint(String expression) {
        if (suspendedThread == null) {
            emit("{\"event\":\"error\",\"detail\":\"No suspended thread\"}");
            return;
        }
        try {
            StackFrame frame = suspendedThread.frame(0);
            for (LocalVariable variable : frame.visibleVariables()) {
                if (variable.name().equals(expression)) {
                    Value value = frame.getValue(variable);
                    emit("{\"event\":\"print\",\"command\":\"print " + esc(expression) + "\",\"output\":\"" + esc(String.valueOf(value)) + "\"}");
                    return;
                }
            }
            emit("{\"event\":\"print\",\"command\":\"print " + esc(expression) + "\",\"output\":\"not a visible local\"}");
        } catch (Exception ex) {
            emit("{\"event\":\"error\",\"detail\":\"" + esc(ex.toString()) + "\"}");
        }
    }

    private static void reportCurrent(String kind) {
        if (suspendedThread == null) {
            emit("{\"event\":\"error\",\"detail\":\"No suspended thread\"}");
            return;
        }
        try {
            report(suspendedThread, suspendedThread.frame(0).location(), kind);
        } catch (Exception ex) {
            emit("{\"event\":\"error\",\"detail\":\"" + esc(ex.toString()) + "\"}");
        }
    }

    private static EventSet poll(long timeoutMs) throws Exception {
        long deadline = System.currentTimeMillis() + timeoutMs;
        while (System.currentTimeMillis() < deadline) {
            long slice = Math.min(400, deadline - System.currentTimeMillis());
            if (slice <= 0) {
                break;
            }
            EventSet set = vm.eventQueue().remove(slice);
            if (set != null) {
                return set;
            }
        }
        return null;
    }

    private static void report(ThreadReference thread, Location location, String kind) {
        StringBuilder locals = new StringBuilder();
        StringBuilder frames = new StringBuilder();
        try {
            StackFrame frame = thread.frame(0);
            try {
                for (LocalVariable variable : frame.visibleVariables()) {
                    Value value = frame.getValue(variable);
                    if (locals.length() > 0) {
                        locals.append(',');
                    }
                    locals.append("{\"name\":\"").append(esc(variable.name())).append("\",\"value\":\"").append(esc(String.valueOf(value))).append("\"}");
                }
            } catch (AbsentInformationException ex) {
                locals.append("{\"name\":\"locals\",\"value\":\"absent — compile with javac -g\"}");
            }
            int count = Math.min(thread.frameCount(), 8);
            for (int i = 0; i < count; i++) {
                if (frames.length() > 0) {
                    frames.append(',');
                }
                frames.append("\"").append(esc(thread.frame(i).location().toString())).append("\"");
            }
        } catch (Exception ex) {
            locals.append("{\"name\":\"error\",\"value\":\"").append(esc(ex.toString())).append("\"}");
        }
        String where = location == null ? "" : location.toString();
        emit("{\"event\":\"" + kind + "\",\"command\":\"" + esc(where) + "\",\"thread\":\"" + esc(thread.name())
                + "\",\"locals\":[" + locals + "],\"frames\":[" + frames + "],\"output\":\"" + esc(where) + "\"}");
    }

    private static List<Location> lineLocations(ReferenceType type, int line) {
        List<Location> found = new ArrayList<Location>();
        try {
            for (com.sun.jdi.Method method : type.methods()) {
                found.addAll(method.locationsOfLine(line));
            }
        } catch (AbsentInformationException ex) {
            emit("{\"event\":\"error\",\"detail\":\"line table missing; compile the application with javac -g\"}");
        }
        return found;
    }

    private static VirtualMachine attach(String host, String port) throws Exception {
        AttachingConnector connector = null;
        for (AttachingConnector candidate : Bootstrap.virtualMachineManager().attachingConnectors()) {
            if ("com.sun.jdi.SocketAttach".equals(candidate.name())) {
                connector = candidate;
            }
        }
        if (connector == null) {
            throw new IllegalStateException("SocketAttach connector is missing from this JDK");
        }
        Map<String, Connector.Argument> arguments = connector.defaultArguments();
        arguments.get("hostname").setValue(host);
        arguments.get("port").setValue(port);
        return connector.attach(arguments);
    }

    private static void detach() {
        if (vm == null) {
            return;
        }
        try {
            vm.resume();
        } catch (Exception ignored) {
            // already running
        }
        try {
            vm.dispose();
        } catch (Exception ignored) {
            // detach
        }
        vm = null;
    }

    private static String threadList(VirtualMachine machine) {
        StringBuilder builder = new StringBuilder();
        for (ThreadReference thread : machine.allThreads()) {
            if (builder.length() > 0) {
                builder.append(", ");
            }
            builder.append(thread.name());
        }
        return builder.toString();
    }

    private static String arg(String[] args, String name, String fallback) {
        for (int i = 0; i < args.length - 1; i++) {
            if (name.equals(args[i])) {
                return args[i + 1];
            }
        }
        return fallback;
    }

    private static String esc(String value) {
        if (value == null) {
            return "";
        }
        return value.replace("\\", "\\\\").replace("\"", "\\\"").replace("\r", "").replace("\n", "\\n");
    }

    private static void emit(String json) {
        System.out.println(json);
        System.out.flush();
    }
}
