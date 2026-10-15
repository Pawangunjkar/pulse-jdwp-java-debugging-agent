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
import com.sun.jdi.event.Event;
import com.sun.jdi.event.EventSet;
import com.sun.jdi.event.ExceptionEvent;
import com.sun.jdi.request.BreakpointRequest;
import com.sun.jdi.request.EventRequest;
import com.sun.jdi.request.ExceptionRequest;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/** Line-delimited JSON JDWP inspector. One process, one attach, then exit. */
public class AgentDebug {
    public static void main(String[] args) throws Exception {
        String host = arg(args, "--host", "127.0.0.1");
        String port = arg(args, "--port", "5005");
        String breaks = arg(args, "--break", "");
        String exception = arg(args, "--catch", "");
        long timeout = Long.parseLong(arg(args, "--timeout", "8")) * 1000L;
        VirtualMachine vm = null;
        try {
            vm = attach(host, port);
            emit("{\"event\":\"attach\",\"command\":\"jdi attach " + esc(host) + ":" + esc(port) + "\",\"output\":\"" + esc(threadList(vm)) + "\"}");
            int armed = arm(vm, breaks, exception);
            emit("{\"event\":\"armed\",\"output\":\"breakpoints=" + armed + "\"}");
            if (armed == 0) {
                emit("{\"event\":\"error\",\"detail\":\"No breakpoint or exception request could be armed\"}");
                return;
            }
            vm.resume();
            waitForHit(vm, timeout);
        } catch (Exception ex) {
            emit("{\"event\":\"error\",\"detail\":\"" + esc(ex.toString()) + "\"}");
        } finally {
            if (vm != null) {
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
            }
            emit("{\"event\":\"done\"}");
        }
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

    private static int arm(VirtualMachine vm, String breaks, String exception) {
        int armed = 0;
        if (!breaks.isEmpty()) {
            for (String item : breaks.split(",")) {
                int colon = item.lastIndexOf(':');
                if (colon < 1) {
                    continue;
                }
                String className = item.substring(0, colon);
                int line = Integer.parseInt(item.substring(colon + 1));
                List<ReferenceType> types = vm.classesByName(className);
                for (ReferenceType type : types) {
                    for (Location location : lineLocations(type, line)) {
                        BreakpointRequest request = vm.eventRequestManager().createBreakpointRequest(location);
                        request.setSuspendPolicy(EventRequest.SUSPEND_EVENT_THREAD);
                        request.enable();
                        armed++;
                        emit("{\"event\":\"breakpoint\",\"command\":\"stop at " + esc(className) + ":" + line + "\",\"output\":\"armed\"}");
                    }
                }
                if (types.isEmpty()) {
                    emit("{\"event\":\"breakpoint\",\"command\":\"stop at " + esc(className) + ":" + line + "\",\"output\":\"class not loaded\"}");
                }
            }
        }
        if (!exception.isEmpty()) {
            List<ReferenceType> types = vm.classesByName(exception);
            ReferenceType type = types.isEmpty() ? null : types.get(0);
            ExceptionRequest request = vm.eventRequestManager().createExceptionRequest(type, true, true);
            request.setSuspendPolicy(EventRequest.SUSPEND_EVENT_THREAD);
            request.addClassFilter("com.*");
            request.enable();
            armed++;
            emit("{\"event\":\"catch\",\"command\":\"catch " + esc(exception) + "\",\"output\":\"armed\"}");
        }
        return armed;
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

    private static void waitForHit(VirtualMachine vm, long timeout) throws Exception {
        long deadline = System.currentTimeMillis() + timeout;
        while (System.currentTimeMillis() < deadline) {
            EventSet set = vm.eventQueue().remove(400);
            if (set == null) {
                continue;
            }
            for (Event event : set) {
                if (event instanceof BreakpointEvent) {
                    report(((BreakpointEvent) event).thread(), ((BreakpointEvent) event).location(), "breakpoint");
                    set.resume();
                    return;
                }
                if (event instanceof ExceptionEvent) {
                    report(((ExceptionEvent) event).thread(), ((ExceptionEvent) event).location(), "exception");
                    set.resume();
                    return;
                }
            }
            set.resume();
        }
        emit("{\"event\":\"error\",\"detail\":\"Timed out waiting for a breakpoint or exception\"}");
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
                Location where = thread.frame(i).location();
                if (frames.length() > 0) {
                    frames.append(',');
                }
                frames.append("\"").append(esc(where.toString())).append("\"");
            }
        } catch (Exception ex) {
            locals.append("{\"name\":\"error\",\"value\":\"").append(esc(ex.toString())).append("\"}");
        }
        String where = location == null ? "" : location.toString();
        emit("{\"event\":\"" + kind + "\",\"command\":\"" + esc(where) + "\",\"thread\":\"" + esc(thread.name())
                + "\",\"locals\":[" + locals + "],\"frames\":[" + frames + "],\"output\":\"" + esc(where) + "\"}");
    }

    private static String threadList(VirtualMachine vm) {
        StringBuilder builder = new StringBuilder();
        for (ThreadReference thread : vm.allThreads()) {
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
