"""JDWP session controller.

Attaches with the JDK's JDI tools (com.sun.jdi.SocketAttach) so Tomcat, WebLogic,
WebSphere, and a plain JVM all use the same handshake. Set JDWP_SIMULATE=true to
exercise the console when no debug port is listening.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import Any

HELPER = Path(__file__).resolve().parent / "AgentDebug.java"
CLASSES = Path(__file__).resolve().parent / "classes"


def jdk_home() -> Path | None:
    candidates = []
    if os.environ.get("JAVA_HOME"):
        candidates.append(Path(os.environ["JAVA_HOME"]))
    candidates.append(Path(r"C:\Program Files\Java\jdk1.8.0_202"))
    java = shutil.which("java")
    if java:
        candidates.append(Path(java).resolve().parents[1])
    for home in candidates:
        binary = home / "bin" / ("java.exe" if os.name == "nt" else "java")
        tools = home / "lib" / "tools.jar"
        if binary.is_file() and tools.is_file():
            return home
    return None


class JdwpEngine:
    def __init__(self) -> None:
        self.proc: asyncio.subprocess.Process | None = None
        self.host = ""
        self.port = 0
        self._lines: list[dict[str, Any]] = []

    @property
    def simulate(self) -> bool:
        return os.environ.get("JDWP_SIMULATE", "true").lower() in {"1", "true", "yes"}

    async def attach_session(self, host: str, jdwp_port: int, source_paths: list[str] | None = None) -> dict[str, Any]:
        self.host = host
        self.port = jdwp_port
        if self.simulate:
            return {"connected": True, "mode": "simulate", "detail": f"Simulated attach {host}:{jdwp_port}", "sourcePaths": source_paths or []}
        if jdk_home() is None:
            return {"connected": False, "mode": "unavailable", "detail": "JDK with lib/tools.jar was not found. Set JAVA_HOME to a JDK 8+ home that contains tools.jar."}
        return {"connected": True, "mode": "jdi", "detail": f"JDI SocketAttach ready for {host}:{jdwp_port}", "sourcePaths": source_paths or []}

    async def inspect(self, host: str, port: int, breakpoints: list[tuple[str, int]], exception: str | None = None) -> dict[str, Any]:
        self.host = host
        self.port = port
        if self.simulate or port <= 0:
            return self._simulated(breakpoints)
        home = jdk_home()
        if home is None:
            return {"connected": False, "mode": "unavailable", "detail": "JDK with tools.jar was not found", "events": [], "locals": [], "frames": [], "threads": []}
        java = home / "bin" / ("java.exe" if os.name == "nt" else "java")
        javac = home / "bin" / ("javac.exe" if os.name == "nt" else "javac")
        tools = home / "lib" / "tools.jar"
        CLASSES.mkdir(parents=True, exist_ok=True)
        compile = await asyncio.create_subprocess_exec(
            str(javac),
            "-cp",
            str(tools),
            "-d",
            str(CLASSES),
            str(HELPER),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        compile_out = (await compile.stdout.read()).decode(errors="replace") if compile.stdout else ""
        if await compile.wait() != 0:
            return {"connected": False, "mode": "jdi", "detail": compile_out[-400], "events": [], "locals": [], "frames": [], "threads": []}
        separator = ";" if os.name == "nt" else ":"
        command = [
            str(java),
            "-cp",
            f"{CLASSES}{separator}{tools}",
            "com.pulse.jdwp.AgentDebug",
            "--host",
            host,
            "--port",
            str(port),
            "--timeout",
            "8",
        ]
        if breakpoints:
            command.extend(["--break", ",".join(f"{class_name}:{line}" for class_name, line in breakpoints)])
        if exception:
            command.extend(["--catch", exception])
        self.proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        raw = await asyncio.wait_for(self.proc.stdout.read(), timeout=20) if self.proc.stdout else b""
        await self.proc.wait()
        events = []
        for line in raw.decode(errors="replace").splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    events.append({"event": "output", "output": line})
        hit = next((item for item in events if item.get("event") in {"breakpoint", "exception"} and item.get("locals")), None)
        error = next((item for item in events if item.get("event") == "error"), None)
        attach = next((item for item in events if item.get("event") == "attach"), None)
        connected = attach is not None and hit is not None
        return {
            "connected": connected,
            "mode": "jdi",
            "detail": (error or attach or {"output": raw.decode(errors="replace")[-400]}).get("detail") or (error or attach or {}).get("output", ""),
            "events": events,
            "locals": (hit or {}).get("locals") or [],
            "frames": (hit or {}).get("frames") or [],
            "threads": [(attach or {}).get("output", "")],
            "thread": (hit or {}).get("thread", "main"),
        }

    def _simulated(self, breakpoints: list[tuple[str, int]]) -> dict[str, Any]:
        return {
            "connected": True,
            "mode": "simulate",
            "detail": f"Simulated attach {self.host}:{self.port}",
            "events": [{"event": "breakpoint", "command": f"stop at {name}:{line}", "output": "simulated"} for name, line in breakpoints],
            "locals": [{"name": "taxable", "value": "null"}, {"name": "orderId", "value": "8c2e-demo"}],
            "frames": ["CheckoutSaga.capture(CheckoutSaga.java:18)"],
            "threads": ["main"],
            "thread": "main",
        }

    async def set_breakpoint(self, class_name: str, line_number: int, condition: str | None = None) -> str:
        return f"stop at {class_name}:{line_number}" + (f" if {condition}" if condition else "")

    async def catch_exception(self, exception_class: str) -> str:
        return f"catch {exception_class}"

    async def inspect_threads_and_frames(self) -> str:
        return "threads via JDI"

    async def dump_local_variables(self, thread_id: str, frame_index: int) -> dict[str, Any]:
        return {"threadId": thread_id, "frame": frame_index, "locals": []}

    async def evaluate_expression(self, expression: str) -> str:
        return expression

    async def resume_or_step(self, action: str = "cont") -> str:
        return action

    async def close(self) -> None:
        if self.proc and self.proc.returncode is None:
            self.proc.kill()
        self.proc = None
