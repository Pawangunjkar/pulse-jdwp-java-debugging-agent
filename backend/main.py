"""PulseJDWP API. The console opens on the home page. There is no auth gate."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langgraph.errors import GraphInterrupt
from langgraph.types import Command

from backend.agent.graph import GRAPH
from backend.jdwp.engine import forget, get_engine
from backend.skills.registry import delete_skill, get_skill, list_skills, save_skill
from backend.store import STORE

app = FastAPI(title="PulseJDWP", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def public_session(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": state["session_id"],
        "targetId": state.get("target_id"),
        "status": state.get("status"),
        "summary": state.get("root_cause_summary") or "Waiting for the agent.",
        "stepper": state.get("stepper"),
        "stack": state.get("issue_stack_trace"),
        "frames": state.get("parsed_frames") or [],
        "breakpoints": state.get("breakpoints") or [],
        "variables": state.get("captured_variables") or [],
        "threads": state.get("thread_dumps") or [],
        "startupScript": state.get("startup_script_path"),
        "startupText": state.get("startup_script_text"),
        "jdwpPort": state.get("discovered_jdwp_port"),
        "jdwpConnected": get_engine(state["session_id"]) is not None,
        "sourceSnippet": state.get("source_snippet") or "",
        "runtimeFamily": state.get("runtime_family") or "",
        "skills": state.get("active_skill_ids") or [],
        "extraContext": state.get("extra_context"),
        "pending": state.get("pending_human_approval"),
        "createdAt": state.get("created_at"),
        "events": state.get("events") or [],
    }


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/targets")
def targets() -> list[dict[str, Any]]:
    rows = []
    for target in STORE.targets.values():
        latest = next(
            (public_session(session) for session in reversed(list(STORE.sessions.values())) if session.get("target_id") == target["id"]),
            None,
        )
        rows.append({**target, "latestSession": latest})
    return rows


@app.post("/api/targets")
def create_target(body: dict[str, Any]) -> dict[str, Any]:
    target_id = body["name"].lower().replace(" ", "-")
    STORE.targets[target_id] = {
        "id": target_id,
        "name": body["name"],
        "domain": body.get("domain", "Core JVM"),
        "startupScript": body.get("startupScript", ""),
        "packagePrefix": body.get("packagePrefix", "com.example"),
        "jdwpPort": int(body.get("jdwpPort") or 5005),
        "host": body.get("host", "127.0.0.1"),
        "skills": body.get("skills") or [],
    }
    return STORE.targets[target_id]


@app.get("/api/skills")
def skills() -> list[dict[str, Any]]:
    return list_skills()


@app.post("/api/skills")
def create_skill(body: dict[str, Any]) -> dict[str, Any]:
    return save_skill(body)


@app.put("/api/skills/{skill_id}")
def update_skill(skill_id: str, body: dict[str, Any]) -> dict[str, Any]:
    body["id"] = skill_id
    return save_skill(body)


@app.delete("/api/skills/{skill_id}")
def remove_skill(skill_id: str) -> dict[str, bool]:
    if not delete_skill(skill_id):
        raise HTTPException(404, "Skill not found")
    return {"deleted": True}


@app.get("/api/sessions")
def sessions(status: str | None = None) -> list[dict[str, Any]]:
    rows = [public_session(item) for item in STORE.sessions.values()]
    if status:
        rows = [row for row in rows if row["status"] == status]
    return rows


@app.get("/api/sessions/{session_id}")
def session_detail(session_id: str) -> dict[str, Any]:
    state = STORE.sessions.get(session_id)
    if not state:
        raise HTTPException(404, "Debug Session not found")
    return public_session(state)


@app.post("/api/sessions")
async def start_session(body: dict[str, Any]) -> dict[str, Any]:
    target_id = body["targetId"]
    if target_id not in STORE.targets:
        raise HTTPException(404, "Application Target not found")
    state = STORE.create_session(target_id, body.get("stack") or "", body.get("extraContext") or "", body.get("skillIds") or [])
    asyncio.create_task(_run(state["session_id"]))
    return public_session(state)


async def _run(session_id: str, resume: dict[str, Any] | None = None) -> None:
    config = {"configurable": {"thread_id": session_id}}
    incoming: Any = Command(resume=resume) if resume else STORE.sessions[session_id]
    try:
        async for event in GRAPH.astream_events(incoming, config=config, version="v2"):
            kind = event.get("event")
            if kind == "on_chain_end":
                output = event.get("data", {}).get("output")
                if isinstance(output, dict):
                    STORE.sessions[session_id].update({key: value for key, value in output.items() if key != "events"})
        STORE.save()
    except GraphInterrupt:
        STORE.sessions[session_id]["status"] = "attention"
        STORE.save()
        return
    except Exception as exc:
        STORE.emit(session_id, "lifecycle_step", status="danger", detail=str(exc), stepper=STORE.sessions[session_id].get("stepper"))
        STORE.sessions[session_id]["status"] = "danger"
        STORE.sessions[session_id]["root_cause_summary"] = str(exc)
        STORE.save()


@app.get("/api/sessions/{session_id}/stream")
async def stream(session_id: str) -> StreamingResponse:
    if session_id not in STORE.sessions:
        raise HTTPException(404, "Debug Session not found")

    async def frames():
        queue = STORE.queues[session_id]
        while True:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        history = list(STORE.sessions[session_id].get("events") or [])
        for event in history:
            yield f"data: {json.dumps(event)}\n\n"
            if event.get("kind") == "lifecycle_step" and event.get("status") in {"success", "danger"} and event.get("stepper") == "Root Cause Synthesized":
                return
        while True:
            event = await queue.get()
            yield f"data: {json.dumps(event)}\n\n"
            if event.get("kind") == "lifecycle_step" and event.get("status") in {"success", "danger"} and event.get("stepper") == "Root Cause Synthesized":
                break

    return StreamingResponse(frames(), media_type="text/event-stream")


@app.post("/api/sessions/{session_id}/debug")
async def debug_action(session_id: str, body: dict[str, Any]) -> dict[str, Any]:
    engine = get_engine(session_id)
    if engine is None or session_id not in STORE.sessions:
        raise HTTPException(409, "No live JDWP session for this Debug Session")
    action = str(body.get("action") or "")
    if action == "print":
        line = "print " + str(body.get("expression") or "")
    elif action == "detach":
        line = "exit"
    elif action in {"step", "next", "cont", "locals", "where", "threads"}:
        line = action
    else:
        raise HTTPException(400, "Unsupported debug action")
    events = await engine.command(line)
    hit = next((item for item in events if item.get("locals")), None)
    for item in events:
        if item.get("event") == "ready":
            continue
        STORE.emit(session_id, "jdwp_event", event=item.get("event"), command=item.get("command"), output=item.get("output") or item.get("detail") or "", detail=item)
    if hit:
        STORE.sessions[session_id]["captured_variables"] = [{"threadId": hit.get("thread") or "main", "frame": 0, "locals": hit.get("locals") or []}]
        STORE.sessions[session_id]["thread_dumps"] = hit.get("frames") or []
    if action == "detach":
        forget(session_id)
        STORE.sessions[session_id]["jdwp_connected"] = False
    STORE.save()
    return {"events": events, "session": public_session(STORE.sessions[session_id])}


@app.patch("/api/sessions/{session_id}")
def update_session(session_id: str, body: dict[str, Any]) -> dict[str, Any]:
    state = STORE.sessions.get(session_id)
    if not state:
        raise HTTPException(404, "Debug Session not found")
    if "extraContext" in body:
        state["extra_context"] = body.get("extraContext") or ""
    if "skillIds" in body:
        state["active_skill_ids"] = body.get("skillIds") or []
    STORE.save()
    return public_session(state)


@app.get("/api/settings")
def read_settings() -> dict[str, str]:
    return STORE.settings


@app.put("/api/settings")
def write_settings(body: dict[str, Any]) -> dict[str, str]:
    if body.get("command"):
        STORE.settings["command"] = str(body["command"])
    if body.get("patterns"):
        STORE.settings["patterns"] = str(body["patterns"])
    STORE.save()
    return STORE.settings


@app.get("/api/queue")
def queue() -> list[dict[str, Any]]:
    rows = []
    for state in STORE.sessions.values():
        pending = state.get("pending_human_approval")
        if not pending:
            continue
        frame = next((item for item in state.get("parsed_frames") or [] if item.get("applicationFrame")), {})
        rows.append(
            {
                "sessionId": state["session_id"],
                "targetId": state.get("target_id"),
                "bucket": pending.get("kind"),
                "summary": pending.get("summary"),
                "waited": state.get("created_at"),
                "diff": pending.get("diff"),
                "line": f"{frame.get('className')}:{frame.get('line')}" if frame else "",
            }
        )
    return rows


@app.post("/api/queue/{session_id}/approve")
async def approve(session_id: str, body: dict[str, Any]) -> dict[str, Any]:
    if session_id not in STORE.sessions:
        raise HTTPException(404, "Debug Session not found")
    approved = bool(body.get("approved", True))
    snapshot = GRAPH.get_state({"configurable": {"thread_id": session_id}})
    if not snapshot.next:
        state = STORE.sessions[session_id]
        state["pending_human_approval"] = None
        state["status"] = "info" if approved else "danger"
        state["stepper"] = "SSH MCP Startup Check"
        STORE.emit(session_id, "lifecycle_step", status=state["status"], stepper=state["stepper"], detail="approved" if approved else "rejected")
        return {"sessionId": session_id, "approved": approved}
    asyncio.create_task(_run(session_id, {"approved": approved}))
    return {"sessionId": session_id, "approved": approved}


@app.get("/api/summary")
def summary() -> dict[str, int]:
    sessions = list(STORE.sessions.values())
    return {
        "active": sum(1 for item in sessions if item.get("status") == "agent"),
        "queue": sum(1 for item in sessions if item.get("pending_human_approval")),
        "targets": len(STORE.targets),
        "skills": len(list_skills()),
        "resolved": sum(1 for item in sessions if item.get("status") == "success"),
    }


def skill_or_404(skill_id: str) -> dict[str, Any]:
    skill = get_skill(skill_id)
    if not skill:
        raise HTTPException(404, "Skill not found")
    return skill
