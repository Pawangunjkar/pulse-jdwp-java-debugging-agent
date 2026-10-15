"""Parse Java stack frames and rank breakpoint candidates."""

from __future__ import annotations

import os
import re
from typing import Any

FRAME = re.compile(
    r"at\s+(?P<cls>[\w.$]+)\.(?P<method>[\w$<>]+)\((?P<file>[\w.$]+):(?P<line>\d+)\)"
)


def parse_stack(text: str, prefixes: list[str] | None = None) -> list[dict[str, Any]]:
    raw = os.environ.get("APP_PACKAGE_PREFIXES", "com.ecs,com.example")
    env_prefixes = [item.strip() for item in raw.split(",") if item.strip()]
    prefixes = list(dict.fromkeys([*(prefixes or []), *env_prefixes])) or env_prefixes
    frames: list[dict[str, Any]] = []
    for index, line in enumerate(text.splitlines()):
        match = FRAME.search(line)
        if not match:
            continue
        class_name = match.group("cls")
        owned = any(class_name.startswith(prefix) for prefix in prefixes) if prefixes else True
        frames.append(
            {
                "index": index,
                "className": class_name,
                "method": match.group("method"),
                "file": match.group("file"),
                "line": int(match.group("line")),
                "applicationFrame": owned,
                "rank": 0 if owned else 50 + index,
            }
        )
    frames.sort(key=lambda frame: (frame["rank"], frame["index"]))
    return frames
