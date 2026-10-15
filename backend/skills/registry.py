"""Hot-reloadable debugging skills stored as Markdown."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

SKILLS_DIR = Path(__file__).resolve().parent

FRONT = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.S)


def _split(text: str) -> tuple[dict[str, str], str]:
    match = FRONT.match(text.strip() + "\n" if not text.endswith("\n") else text)
    meta: dict[str, str] = {}
    body = text
    if match:
        body = match.group(2).strip()
        for line in match.group(1).splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                meta[key.strip()] = value.strip()
    return meta, body


def list_skills() -> list[dict[str, Any]]:
    skills = []
    for path in sorted(SKILLS_DIR.glob("*.md")):
        meta, body = _split(path.read_text(encoding="utf-8"))
        skills.append(
            {
                "id": meta.get("id", path.stem),
                "name": meta.get("name", path.stem),
                "description": meta.get("description", ""),
                "domain": meta.get("domain", "Core JVM"),
                "triggerPatterns": [item.strip() for item in meta.get("triggers", "").split(",") if item.strip()],
                "systemInstructions": body,
                "customCommands": [item.strip() for item in meta.get("commands", "").split("|") if item.strip()],
            }
        )
    return skills


def get_skill(skill_id: str) -> dict[str, Any] | None:
    return next((skill for skill in list_skills() if skill["id"] == skill_id), None)


def save_skill(payload: dict[str, Any]) -> dict[str, Any]:
    skill_id = re.sub(r"[^a-z0-9-]", "-", payload["id"].lower()).strip("-")
    triggers = ",".join(payload.get("triggerPatterns") or [])
    commands = "|".join(payload.get("customCommands") or [])
    text = (
        f"---\nid: {skill_id}\nname: {payload['name']}\n"
        f"description: {payload.get('description', '')}\n"
        f"domain: {payload.get('domain', 'Core JVM')}\n"
        f"triggers: {triggers}\ncommands: {commands}\n---\n\n"
        f"{payload.get('systemInstructions', '')}\n"
    )
    (SKILLS_DIR / f"{skill_id}.md").write_text(text, encoding="utf-8")
    skill = get_skill(skill_id)
    if skill is None:
        raise RuntimeError(f"Skill {skill_id} was not saved")
    return skill


def delete_skill(skill_id: str) -> bool:
    path = SKILLS_DIR / f"{skill_id}.md"
    if not path.is_file():
        return False
    path.unlink()
    return True


def match_skills(stack: str, selected: list[str]) -> list[dict[str, Any]]:
    chosen = []
    for skill in list_skills():
        if skill["id"] in selected:
            chosen.append(skill)
            continue
        if any(pattern and pattern in stack for pattern in skill["triggerPatterns"]):
            chosen.append(skill)
    return chosen
