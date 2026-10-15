"""LangGraph session state for a remote JDWP debug run."""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages


class DebugSessionState(TypedDict, total=False):
    session_id: str
    target_id: str
    status: str
    issue_stack_trace: str
    parsed_frames: list[dict[str, Any]]
    extra_context: str
    active_skill_ids: list[str]
    skill_instructions: str
    startup_script_path: str
    startup_script_text: str
    host: str
    runtime_family: str
    discovered_jdwp_port: int | None
    jdwp_connected: bool
    breakpoints: list[dict[str, Any]]
    captured_variables: list[dict[str, Any]]
    thread_dumps: list[str]
    pending_human_approval: dict[str, Any] | None
    approval: dict[str, Any] | None
    messages: Annotated[list, add_messages]
    root_cause_summary: str
    created_at: str
    events: list[dict[str, Any]]
    stepper: str


def new_state(session_id: str, target_id: str, stack: str, extra: str) -> DebugSessionState:
    return DebugSessionState(
        session_id=session_id,
        target_id=target_id,
        status="neutral",
        issue_stack_trace=stack,
        parsed_frames=[],
        extra_context=extra,
        active_skill_ids=[],
        skill_instructions="",
        startup_script_path="",
        startup_script_text="",
        discovered_jdwp_port=None,
        jdwp_connected=False,
        breakpoints=[],
        captured_variables=[],
        thread_dumps=[],
        pending_human_approval=None,
        approval=None,
        messages=[],
        root_cause_summary="",
        events=[],
        stepper="Stack Ingested",
    )
