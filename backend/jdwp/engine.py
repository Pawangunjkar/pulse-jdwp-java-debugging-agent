"""Long-lived JDWP session.

The helper process stays attached until the operator detaches. Commands are
step, next, cont, locals, where, threads, and print. Compilation uses the
running JDK's jdk.jdi module when tools.jar is absent.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

HELPER = Path(__file__).resolve().parent / "AgentDebug.java"
CLASSES = Path(__file__).resolve().parent / "classes"
SECRET = re.compile(r"password|passwd|secret|token|pan|cvv|authorization|api[-_]?key", re.I)
OPEN: dict[str, "JdwpEngine"] = {}
_COMPILE: list[str] | None = None


def jdk_home() -> Path | None:
    candidates: list[Path] = []
    if os.environ.get("JAVA_HOME"):
        candidates.append(Path(os.environ["JAVA_HOME"]))
    java = shutil.which("java")
    if java:
        candidates.append(Path(java).resolve().parents[1])
    candidates.append(Path(r"C:\Program Files\Java\jdk1.8.0_202"))
    for home in candidates:
        binary = home / "bin" / ("java.exe" if os.name == "nt" else "java")
        if binary.is_file() and (_has_jdi_module(binary) or (home / "lib" / "tools.jar").is_file()):
            return home
    return None


def _has_jdi_module(java: Path) -> bool:
    try:
        listing = subprocess.run([str(java), "--list-modules"], capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "jdk.jdi" in listing.stdout


def redact_locals(locals_: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    cleaned = []
    for item in locals_ or []:
        name = str(item.get("name", ""))
        value = item.get("value")
        if SECRET.search(name):
            value = "***"
        cleaned.append({**item, "value": value})
    return cleaned


def redact_event(event: dict[str, Any]) -> dict[str, Any]:
    if "locals" in event:
        event = {**event, "locals": redact_locals(event.get("locals"))}
    return event


class JdwpEngine:
    def __init__(self) -> None:
        self.proc: asyncio.subprocess.Process | None = None
        self.host = ""
        self.port = 0
        self.mode = "jdi"

    @property
    def simulate(self) -> bool:
        return os.environ.get("JDWP_SIMULATE", "true").lower() in {"1", "true", "yes"}

    async def open(self, host: str, port: int) -> dict[str, Any]:
        self.host = host
        self.port = port
        if self.simulate or port <= 0:
            self.mode = "simulate"
            return {"connected": True, "mode": "simulate", "events": [{"event": "attach", "command": f"simulate {host}:{port}", "output": "simulated"}]}
        launch = _launch_command()
        if launch is None:
            return {"connected": False, "mode": "unavailable", "detail": "No JDK with jdk.jdi or tools.jar was found", "events": []}
        self.proc = await asyncio.create_subprocess_exec(
            *launch,
            "--host",
            host,
            "--port",
            str(port),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        events = await self._read_until_ready()
        attach = next((item for item in events if item.get("event") == "attach"), None)
        error = next((item for item in events if item.get("event") == "error"), None)
        return {
            "connected": attach is not None and error is None,
            "mode": "jdi",
            "detail": (error or {}).get("detail") or (attach or {}).get("output", ""),
            "events": events,
        }

    async def command(self, line: str) -> list[dict[str, Any]]:
        if self.mode == "simulate":
            return [_simulated_command(line), {"event": "ready"}]
        if self.proc is None or self.proc.stdin is None:
            return [{"event": "error", "detail": "JDWP session is not open"}]
        self.proc.stdin.write((line + "\n").encode())
        await self.proc.stdin.drain()
        events = await self._read_until_ready()
        if line == "exit":
            await self.close()
        return events

    async def _read_until_ready(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        if self.proc is None or self.proc.stdout is None:
            return events
        while True:
            try:
                raw = await asyncio.wait_for(self.proc.stdout.readline(), timeout=20)
            except TimeoutError:
                events.append({"event": "error", "detail": "Timed out waiting for the debugger"})
                break
            if not raw:
                events.append({"event": "error", "detail": "Debugger process closed its output"})
                break
            text = raw.decode(errors="replace").strip()
            if not text.startswith("{"):
                continue
            try:
                event = redact_event(json.loads(text))
            except json.JSONDecodeError:
                event = {"event": "output", "output": text}
            events.append(event)
            if event.get("event") == "ready":
                break
        return events

    async def close(self) -> None:
        if self.proc and self.proc.returncode is None:
            self.proc.kill()
        self.proc = None


def get_engine(session_id: str) -> JdwpEngine | None:
    return OPEN.get(session_id)


def remember(session_id: str, engine: JdwpEngine) -> None:
    OPEN[session_id] = engine


def forget(session_id: str) -> None:
    OPEN.pop(session_id, None)


def _launch_command() -> list[str] | None:
    global _COMPILE
    if _COMPILE:
        return list(_COMPILE)
    home = jdk_home()
    if home is None:
        return None
    binary = "java.exe" if os.name == "nt" else "java"
    compiler = "javac.exe" if os.name == "nt" else "javac"
    java = home / "bin" / binary
    javac = home / "bin" / compiler
    tools = home / "lib" / "tools.jar"
    CLASSES.mkdir(parents=True, exist_ok=True)
    if _has_jdi_module(java):
        compile = [str(javac), "--add-modules", "jdk.jdi", "-d", str(CLASSES), str(HELPER)]
        run = [str(java), "--add-modules", "jdk.jdi", "-cp", str(CLASSES), "com.pulse.jdwp.AgentDebug"]
    elif tools.is_file():
        compile = [str(javac), "-cp", str(tools), "-d", str(CLASSES), str(HELPER)]
        separator = ";" if os.name == "nt" else ":"
        run = [str(java), "-cp", f"{CLASSES}{separator}{tools}", "com.pulse.jdwp.AgentDebug"]
    else:
        return None
    compiled = subprocess.run(compile, capture_output=True, text=True, check=False)
    if compiled.returncode != 0:
        raise RuntimeError((compiled.stdout + compiled.stderr)[-500:])
    _COMPILE = run
    return list(run)


def _simulated_command(line: str) -> dict[str, Any]:
    locals_ = redact_locals([{"name": "taxable", "value": "null"}, {"name": "orderId", "value": "8c2e-demo"}])
    frames = ["com.example.checkout.CheckoutSaga:18", "com.example.checkout.CheckoutSaga:9"]
    if line.startswith("print "):
        name = line.split(None, 1)[1]
        value = next((item["value"] for item in locals_ if item["name"] == name), "not a visible local")
        return {"event": "print", "command": line, "output": value}
    return {"event": line.split()[0], "command": line, "output": "simulated", "locals": locals_, "frames": frames, "thread": "main"}


def source_snippet(source_root: str, file_name: str, line: int, radius: int = 3) -> str:
    if not source_root or not file_name or line <= 0:
        return ""
    root = Path(source_root)
    matches = [root / file_name]
    if root.is_dir():
        matches.extend(root.rglob(file_name))
    for path in matches:
        if not path.is_file():
            continue
        rows = path.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, line - radius)
        end = min(len(rows), line + radius)
        picked = [f"{index}: {rows[index - 1]}" for index in range(start, end + 1)]
        return "\n".join(picked)
    return ""
