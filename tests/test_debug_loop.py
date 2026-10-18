"""Parser, redaction, source lookup, and a live JDWP step."""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

from backend.jdwp.engine import redact_locals, source_snippet
from backend.mcp.ssh_mcp_client import extract_port, inject_flag, restart_command, server_family

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "samples" / "checkout"


class ScriptTests(unittest.TestCase):
    def test_server_families_and_localhost_flag(self) -> None:
        os.environ["JDWP_BIND_ALL"] = "false"
        tomcat = (SAMPLE / "tomcat" / "bin" / "setenv.sh").read_text(encoding="utf-8")
        weblogic = (SAMPLE / "weblogic" / "bin" / "setDomainEnv.sh").read_text(encoding="utf-8")
        websphere = (SAMPLE / "websphere" / "server.xml").read_text(encoding="utf-8")
        self.assertEqual(server_family(tomcat, "tomcat/bin/setenv.sh"), "Tomcat")
        self.assertEqual(server_family(weblogic, "setDomainEnv.sh"), "WebLogic")
        self.assertEqual(server_family(websphere, "server.xml"), "WebSphere")
        self.assertEqual(extract_port(tomcat), 5010)
        self.assertEqual(extract_port("address=127.0.0.1:5011"), 5011)
        injected = inject_flag("JAVA_OPTS=\n", 5005, "tomcat/bin/setenv.sh")
        self.assertIn("address=127.0.0.1:5005", injected)
        self.assertIn("CATALINA_OPTS", injected)
        self.assertIn("startup.sh", restart_command("Tomcat", str(SAMPLE / "tomcat" / "bin" / "setenv.sh")))

    def test_redact_and_source(self) -> None:
        cleaned = redact_locals([{"name": "password", "value": "secret"}, {"name": "taxable", "value": "null"}])
        self.assertEqual(cleaned[0]["value"], "***")
        self.assertEqual(cleaned[1]["value"], "null")
        snippet = source_snippet(str(SAMPLE / "src"), "CheckoutSaga.java", 18)
        self.assertIn("18:", snippet)
        self.assertIn("taxable.length", snippet)


class LiveAttachTest(unittest.TestCase):
    def test_step_after_breakpoint(self) -> None:
        java = Path(r"C:\Program Files\Java\jdk1.8.0_202\bin\java.exe")
        javac = Path(r"C:\Program Files\Java\jdk1.8.0_202\bin\javac.exe")
        if not java.is_file():
            self.skipTest("JDK 8 is not installed")
        classes = SAMPLE / "classes"
        classes.mkdir(exist_ok=True)
        compiled = subprocess.run(
            [str(javac), "-g", "-d", str(classes), str(SAMPLE / "src" / "com" / "example" / "checkout" / "CheckoutSaga.java")],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(compiled.returncode, 0, compiled.stderr)
        port = 5019
        proc = subprocess.Popen(
            [str(java), f"-agentlib:jdwp=transport=dt_socket,server=y,suspend=n,address={port}", "-cp", str(classes), "com.example.checkout.CheckoutSaga"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            os.environ["JDWP_SIMULATE"] = "false"
            import asyncio

            from backend.jdwp.engine import JdwpEngine

            async def run() -> None:
                engine = JdwpEngine()
                opened = await engine.open("127.0.0.1", port)
                self.assertTrue(opened["connected"], opened)
                await engine.command("break com.example.checkout.CheckoutSaga:18")
                events = await engine.command("wait 8")
                hit = next(item for item in events if item.get("locals"))
                names = {item["name"]: item["value"] for item in hit["locals"]}
                self.assertEqual(names.get("taxable"), "null")
                stepped = await engine.command("next")
                self.assertTrue(any(item.get("event") in {"next", "step"} for item in stepped), stepped)
                await engine.command("exit")

            asyncio.run(run())
        finally:
            proc.kill()
            proc.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
