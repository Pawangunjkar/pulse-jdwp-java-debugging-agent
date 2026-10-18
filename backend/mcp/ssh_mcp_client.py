"""stdio client for the pawangunjkar Linux SSH MCP server."""

from __future__ import annotations

import json
import os
import shlex
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent


def _payload(result: Any) -> str:
    if getattr(result, "structuredContent", None):
        return json.dumps(result.structuredContent)
    texts = []
    for block in getattr(result, "content", []) or []:
        if isinstance(block, TextContent) or getattr(block, "text", None):
            texts.append(block.text)
    return "\n".join(texts)


class SshMcpClient:
    """Connects to linux-ssh-mcp and exposes the startup-script and process tools."""

    def __init__(self) -> None:
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None

    @property
    def configured(self) -> bool:
        return bool(os.environ.get("SSH_MCP_COMMAND") or os.environ.get("SSH_MCP_URL"))

    async def start(self) -> None:
        if self._session is not None:
            return
        command = os.environ.get("SSH_MCP_COMMAND", "uv")
        raw_args = os.environ.get("SSH_MCP_ARGS", "")
        if raw_args.startswith("["):
            args = json.loads(raw_args)
        elif raw_args:
            args = shlex.split(raw_args)
        else:
            args = ["run", "--directory", "../linux-ssh-mcp", "server.py"]
        self._stack = AsyncExitStack()
        await self._stack.__aenter__()
        params = StdioServerParameters(command=command, args=args, env=os.environ.copy())
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        await self.start()
        assert self._session is not None
        result = await self._session.call_tool(name, arguments)
        return _payload(result)

    async def read_script(self, path: str, session_name: str = "default") -> str:
        return await self.call("ssh_read_file", {"path": path, "session_name": session_name})

    async def exec(self, command: str, session_name: str = "default") -> str:
        return await self.call("ssh_execute", {"command": command, "session_name": session_name, "timeout": 30})

    async def write_script(self, path: str, content: str, session_name: str = "default") -> str:
        return await self.call(
            "ssh_write_file",
            {"path": path, "content": content, "session_name": session_name, "append": False},
        )


SSH = SshMcpClient()


def jdwp_flag(port: int) -> str:
    bind_all = os.environ.get("JDWP_BIND_ALL", "").lower() in {"1", "true", "yes"}
    address = f"*:{port}" if bind_all else f"127.0.0.1:{port}"
    return f"-agentlib:jdwp=transport=dt_socket,server=y,suspend=n,address={address}"


def extract_port(script: str) -> int | None:
    import re

    hosted = re.search(r"address=(?:\*|[\d.]+):(\d+)", script)
    if hosted:
        return int(hosted.group(1))
    bare = re.search(r"address=(\d+)\b", script)
    return int(bare.group(1)) if bare else None


def server_family(script: str, path: str = "") -> str:
    blob = f"{path}\n{script}".lower()
    if "weblogic" in blob or "setdomainenv" in blob or "java_options" in blob:
        return "WebLogic"
    if "websphere" in blob or "genericjvmarguments" in blob or "startserver" in blob:
        return "WebSphere"
    if "catalina" in blob or "tomcat" in blob or "setenv.sh" in blob:
        return "Tomcat"
    if "spring" in blob or "quarkus" in blob:
        return "Spring Boot"
    return "JVM"


def restart_command(family: str, script_path: str) -> str:
    path = Path(script_path) if script_path else Path()
    if family == "Tomcat":
        bin_dir = path.parent if path.name == "setenv.sh" else path.parent / "bin"
        return f"'{bin_dir / 'shutdown.sh'}'; '{bin_dir / 'startup.sh'}'"
    if family == "WebLogic":
        return f"'{path.parent / 'startWebLogic.sh'}'"
    if family == "WebSphere":
        return "startServer.sh server1"
    return ""


def inject_flag(script: str, port: int, path: str = "") -> str:
    flag = jdwp_flag(port)
    if "jdwp" in script.lower():
        return script
    family = server_family(script, path)
    lines = [
        f"\n# PulseJDWP {family}. JAVA_TOOL_OPTIONS is read by Tomcat, WebLogic, WebSphere, and a Spring Boot jar.",
        f'JAVA_TOOL_OPTIONS="${{JAVA_TOOL_OPTIONS:-}} {flag}"',
    ]
    if family == "Tomcat":
        lines.append(f'CATALINA_OPTS="${{CATALINA_OPTS:-}} {flag}"')
    elif family == "WebLogic":
        lines.append(f'JAVA_OPTIONS="${{JAVA_OPTIONS:-}} {flag}"')
    elif family == "WebSphere":
        lines.append("# WebSphere: put the same -agentlib:jdwp flag in genericJvmArguments in server.xml")
    return script.rstrip() + "\n" + "\n".join(lines) + "\n"
