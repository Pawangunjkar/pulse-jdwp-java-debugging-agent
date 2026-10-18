"""Shared session state, event bus, and seed catalog."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.agent.state import new_state

DATA = Path(__file__).resolve().parents[1] / "data" / "pulse-state.json"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self) -> None:
        self.targets: dict[str, dict[str, Any]] = {}
        self.sessions: dict[str, dict[str, Any]] = {}
        self.queues: dict[str, asyncio.Queue] = {}
        self.settings: dict[str, str] = {"command": "uv", "patterns": "setenv.sh, start.sh, Dockerfile, *.service"}
        loaded = self._load()
        self._seed_targets()
        if not loaded:
            self._seed_sessions()
        self.save()

    def _root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def _load(self) -> bool:
        if not DATA.is_file():
            return False
        payload = json.loads(DATA.read_text(encoding="utf-8"))
        self.targets = payload.get("targets") or {}
        self.sessions = payload.get("sessions") or {}
        self.settings.update(payload.get("settings") or {})
        for session_id in self.sessions:
            self.queues[session_id] = asyncio.Queue()
        return True

    def save(self) -> None:
        DATA.parent.mkdir(parents=True, exist_ok=True)
        sessions = {}
        for session_id, state in self.sessions.items():
            plain = {key: value for key, value in state.items() if key != "messages"}
            plain["events"] = (plain.get("events") or [])[-500:]
            sessions[session_id] = plain
        DATA.write_text(json.dumps({"targets": self.targets, "sessions": sessions, "settings": self.settings}, indent=2), encoding="utf-8")

    def _seed_targets(self) -> None:
        root = self._root()
        samples = [
            ("order-orchestrator", "Spring Boot", "/opt/ecs/bin/setenv.sh", "com.ecs.oms", 5005),
            ("offer-promotion", "Kafka / Messaging", "/opt/ecs/bin/start.sh", "com.ecs.mec.offer", 5006),
            ("customer-360", "Jakarta EE", "/etc/systemd/system/customer-360.service", "com.ecs.crm", 5007),
            ("tomcat-checkout", "Tomcat", str(root / "samples" / "checkout" / "tomcat" / "bin" / "setenv.sh"), "com.example.checkout", 5010),
            ("weblogic-checkout", "WebLogic", str(root / "samples" / "checkout" / "weblogic" / "bin" / "setDomainEnv.sh"), "com.example.checkout", 5011),
            ("websphere-checkout", "WebSphere", str(root / "samples" / "checkout" / "websphere" / "server.xml"), "com.example.checkout", 5012),
        ]
        for name, domain, script, prefix, port in samples:
            if name in self.targets:
                if name.endswith("checkout") and not self.targets[name].get("sourceRoot"):
                    self.targets[name]["sourceRoot"] = str(root / "samples" / "checkout" / "src")
                continue
            self.targets[name] = {
                "id": name,
                "name": name,
                "domain": domain,
                "startupScript": script,
                "packagePrefix": prefix,
                "jdwpPort": port,
                "host": "127.0.0.1",
                "sourceRoot": str(root / "samples" / "checkout" / "src") if name.endswith("checkout") else "",
                "skills": ["npe-root-cause-tracer"],
            }
        self._seed_sessions()

    def _seed_sessions(self) -> None:
        success = new_state("npe-214", "order-orchestrator", "java.lang.NullPointerException\n\tat com.ecs.oms.saga.CheckoutSagaService.capture(CheckoutSagaService.java:214)\n", "taxable is unset after ATP")
        success.update(
            status="success",
            stepper="Root Cause Synthesized",
            root_cause_summary="taxable is null at CheckoutSagaService.capture:214 because the quote line never set it.",
            parsed_frames=[{"className": "com.ecs.oms.saga.CheckoutSagaService", "method": "capture", "file": "CheckoutSagaService.java", "line": 214, "applicationFrame": True}],
            breakpoints=[{"className": "com.ecs.oms.saga.CheckoutSagaService", "line": 214}],
            captured_variables=[{"threadId": "1", "frame": 0, "locals": [{"name": "taxable", "value": "null"}, {"name": "orderId", "value": "8c2e-demo"}]}],
            thread_dumps=["main  RUNNABLE"],
            startup_script_text="JAVA_TOOL_OPTIONS=-agentlib:jdwp=transport=dt_socket,server=y,suspend=n,address=*:5005",
            active_skill_ids=["npe-root-cause-tracer"],
            created_at=utcnow(),
            events=[{"kind": "llm_token", "at": utcnow(), "token": "taxable is null at capture:214. "}],
        )
        waiting = new_state("offer-64", "offer-promotion", "org.apache.kafka.common.errors.SerializationException\n\tat com.ecs.mec.offer.OfferListener.onMessage(OfferListener.java:64)\n", "payload bytes look like JSON")
        waiting.update(
            status="attention",
            stepper="SSH MCP Startup Check",
            pending_human_approval={
                "kind": "Startup Script & JDWP Port Injection",
                "summary": "Inject JDWP on port 5006 into /opt/ecs/bin/start.sh",
                "diff": "JAVA_TOOL_OPTIONS=-agentlib:jdwp=transport=dt_socket,server=y,suspend=n,address=*:5006",
                "scriptPath": "/opt/ecs/bin/start.sh",
            },
            created_at=utcnow(),
            events=[{"kind": "human_gate", "at": utcnow(), "detail": "Awaiting startup script approval"}],
        )
        self.sessions[success["session_id"]] = success
        self.sessions[waiting["session_id"]] = waiting
        self.queues[success["session_id"]] = asyncio.Queue()
        self.queues[waiting["session_id"]] = asyncio.Queue()

    def emit(self, session_id: str, kind: str, payload: dict[str, Any] | None = None, **extra: Any) -> None:
        event = {"kind": kind, "at": utcnow(), **(payload or {}), **extra}
        session = self.sessions.get(session_id)
        if session is not None:
            session.setdefault("events", []).append(event)
            session["events"] = session["events"][-500:]
            self.save()
        queue = self.queues.get(session_id)
        if queue is not None:
            queue.put_nowait(event)

    def create_session(self, target_id: str, stack: str, extra: str, skill_ids: list[str]) -> dict[str, Any]:
        state = new_state(uuid.uuid4().hex[:12], target_id, stack, extra)
        state["active_skill_ids"] = skill_ids
        state["created_at"] = utcnow()
        target = self.targets.get(target_id, {})
        state["startup_script_path"] = target.get("startupScript", "")
        state["discovered_jdwp_port"] = target.get("jdwpPort")
        state["host"] = target.get("host", "127.0.0.1")
        self.sessions[state["session_id"]] = state
        self.queues[state["session_id"]] = asyncio.Queue()
        self.save()
        return state


STORE = Store()
