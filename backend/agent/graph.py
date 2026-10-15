"""LangGraph debug session. Nodes emit SSE events through the process store."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from backend.agent.state import DebugSessionState
from backend.jdwp.engine import JdwpEngine
from backend.llm.streamer import stream_diagnosis
from backend.mcp.ssh_mcp_client import SSH, extract_port, inject_flag, server_family
from backend.parsers.stacktrace import parse_stack
from backend.skills.registry import match_skills
from backend.store import STORE

memory = MemorySaver()


def _emit(state: DebugSessionState, kind: str, **payload: Any) -> None:
    STORE.emit(state["session_id"], kind, payload)


async def ingest_stack_and_skills(state: DebugSessionState) -> dict[str, Any]:
    target = STORE.targets.get(state.get("target_id") or "", {})
    frames = parse_stack(state.get("issue_stack_trace") or "", [target.get("packagePrefix") or "com.example"])
    skills = match_skills(state.get("issue_stack_trace") or "", state.get("active_skill_ids") or [])
    instructions = "\n\n".join(skill["systemInstructions"] for skill in skills)
    _emit(state, "lifecycle_step", status="info", stepper="Stack Ingested", detail=f"{len(frames)} frames, {len(skills)} skills")
    return {
        "parsed_frames": frames,
        "active_skill_ids": [skill["id"] for skill in skills],
        "skill_instructions": instructions,
        "status": "info",
        "stepper": "Stack Ingested",
    }


async def discover_jdwp_via_ssh_mcp(state: DebugSessionState) -> dict[str, Any]:
    _emit(state, "lifecycle_step", status="info", stepper="SSH MCP Startup Check", detail="Reading startup script")
    script_path = state.get("startup_script_path") or ""
    script = state.get("startup_script_text") or ""
    port = state.get("discovered_jdwp_port")
    session_name = os.environ.get("SSH_SESSION", "default")
    local_script = Path(script_path) if script_path else None
    if local_script and local_script.is_file():
        script = local_script.read_text(encoding="utf-8", errors="replace")
        _emit(state, "mcp_command", command=f"read {script_path}", output=script[:800])
        found = extract_port(script)
        if found:
            port = found
    elif SSH.configured and script_path:
        try:
            script = await SSH.read_script(script_path, session_name)
            _emit(state, "mcp_command", command=f"ssh_read_file {script_path}", output=script[:800])
            ps = await SSH.exec("ps -ef | grep java | grep -v grep", session_name)
            _emit(state, "mcp_command", command="ps -ef | grep java", output=ps[:800])
            listeners = await SSH.exec("ss -tulpn | grep java || true", session_name)
            _emit(state, "mcp_command", command="ss -tulpn", output=listeners[:800])
            found = extract_port(script)
            if found:
                port = found
        except Exception as exc:
            _emit(state, "mcp_command", command="ssh", output=str(exc))
    pending = None
    if script and extract_port(script) is None:
        proposed = inject_flag(script, int(port or 5005), script_path)
        pending = {
            "kind": "Startup Script & JDWP Port Injection",
            "scriptPath": script_path,
            "diff": proposed,
            "summary": f"Inject JDWP on port {port or 5005} into {script_path}",
        }
    elif not script and not port:
        pending = {
            "kind": "Startup Script & JDWP Port Injection",
            "scriptPath": script_path,
            "diff": "",
            "summary": "No JDWP port was discovered. Approve a port before attach.",
        }
    family = server_family(script, script_path)
    _emit(state, "lifecycle_step", status="attention" if pending else "info", stepper="SSH MCP Startup Check", detail=f"{family} port={port}")
    return {
        "startup_script_text": script,
        "discovered_jdwp_port": port,
        "runtime_family": family,
        "pending_human_approval": pending,
        "status": "attention" if pending else "info",
        "stepper": "SSH MCP Startup Check",
    }


async def human_approval_gate(state: DebugSessionState) -> dict[str, Any]:
    pending = state.get("pending_human_approval")
    if not pending:
        return {"status": "info"}
    _emit(state, "human_gate", **pending, status="attention")
    decision = interrupt(pending)
    approved = bool(decision and decision.get("approved"))
    if approved and pending.get("diff") and SSH.configured and pending.get("scriptPath"):
        output = await SSH.write_script(pending["scriptPath"], pending["diff"])
        _emit(state, "mcp_command", command=f"ssh_write_file {pending['scriptPath']}", output=output[:500])
    status = "info" if approved else "danger"
    _emit(state, "lifecycle_step", status=status, stepper="SSH MCP Startup Check", detail="approved" if approved else "rejected")
    return {
        "approval": decision or {"approved": False},
        "pending_human_approval": None,
        "startup_script_text": pending.get("diff") or state.get("startup_script_text"),
        "status": status,
    }


async def jdwp_breakpoint_and_inspect(state: DebugSessionState) -> dict[str, Any]:
    if state.get("status") == "danger":
        return {}
    port = int(state.get("discovered_jdwp_port") or 0)
    host = state.get("host") or "127.0.0.1"
    owned = [frame for frame in (state.get("parsed_frames") or []) if frame.get("applicationFrame")]
    owned.sort(key=lambda frame: frame.get("index", 0))
    top = owned[:1]
    stops = [(frame["className"], int(frame["line"])) for frame in top]
    exception = "java.lang.NullPointerException" if "NullPointerException" in (state.get("issue_stack_trace") or "") else None
    engine = JdwpEngine()
    result = await engine.inspect(host, port, stops, exception)
    for item in result.get("events") or []:
        _emit(
            state,
            "jdwp_event",
            event=item.get("event"),
            command=item.get("command"),
            output=item.get("output") or item.get("detail") or "",
            detail=item,
        )
    if not result.get("connected"):
        detail = result.get("detail") or "JDWP attach failed"
        _emit(state, "lifecycle_step", status="danger", stepper="JDWP Attached", detail=detail)
        return {"jdwp_connected": False, "status": "danger", "stepper": "JDWP Attached", "root_cause_summary": detail}
    breakpoints = [{"className": name, "line": line, "output": "armed"} for name, line in stops]
    captured = [{"threadId": result.get("thread") or "main", "frame": 0, "locals": result.get("locals") or []}]
    _emit(state, "lifecycle_step", status="agent", stepper="Breakpoint & Frame Capture", detail="locals captured")
    return {
        "jdwp_connected": True,
        "breakpoints": breakpoints,
        "captured_variables": captured,
        "thread_dumps": result.get("frames") or result.get("threads") or [],
        "status": "agent",
        "stepper": "Breakpoint & Frame Capture",
    }


async def reason_and_diagnose(state: DebugSessionState) -> dict[str, Any]:
    if state.get("status") == "danger" and not state.get("jdwp_connected"):
        return {}
    _emit(state, "lifecycle_step", status="agent", stepper="Root Cause Synthesized", detail="streaming diagnosis")
    parts: list[str] = []
    async for token in stream_diagnosis(state):
        parts.append(token)
        _emit(state, "llm_token", token=token, status="agent")
    summary = "".join(parts).strip()
    _emit(state, "lifecycle_step", status="success", stepper="Root Cause Synthesized", detail=summary[:180])
    return {"root_cause_summary": summary, "status": "success", "stepper": "Root Cause Synthesized"}


def build_graph():
    graph = StateGraph(DebugSessionState)
    graph.add_node("ingest_stack_and_skills", ingest_stack_and_skills)
    graph.add_node("discover_jdwp_via_ssh_mcp", discover_jdwp_via_ssh_mcp)
    graph.add_node("human_approval_gate", human_approval_gate)
    graph.add_node("jdwp_breakpoint_and_inspect", jdwp_breakpoint_and_inspect)
    graph.add_node("reason_and_diagnose", reason_and_diagnose)
    graph.add_edge(START, "ingest_stack_and_skills")
    graph.add_edge("ingest_stack_and_skills", "discover_jdwp_via_ssh_mcp")
    graph.add_edge("discover_jdwp_via_ssh_mcp", "human_approval_gate")
    graph.add_edge("human_approval_gate", "jdwp_breakpoint_and_inspect")
    graph.add_edge("jdwp_breakpoint_and_inspect", "reason_and_diagnose")
    graph.add_edge("reason_and_diagnose", END)
    return graph.compile(checkpointer=memory)


GRAPH = build_graph()
