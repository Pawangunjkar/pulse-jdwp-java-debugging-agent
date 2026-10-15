"""Token streaming for Gemini and OpenAI-compatible endpoints.

When no API key is set, tokens are produced locally from the captured JDWP state
so the operator console still streams a diagnosis.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator


def _local_diagnosis(state: dict) -> str:
    frames = state.get("parsed_frames") or []
    top = frames[0] if frames else {}
    variables = state.get("captured_variables") or []
    locals_text = ", ".join(
        f"{item.get('name')}={item.get('value')}"
        for block in variables
        for item in block.get("locals", [])
    ) or "no locals captured"
    where = f"{top.get('className', 'unknown')}.{top.get('method', 'unknown')}:{top.get('line', '?')}"
    port = state.get("discovered_jdwp_port")
    return (
        f"Application frame {where} is the first owned frame in the pasted stack. "
        f"JDWP port {port} was the attach target. "
        f"Captured locals: {locals_text}. "
        f"Skill guidance says to name the null or failed payload instead of guessing a fix. "
        f"Next change: guard the null local before the line above, then rerun the same stack."
    )


async def stream_text(text: str) -> AsyncIterator[str]:
    word = ""
    for char in text:
        word += char
        if char in " \n":
            yield word
            word = ""
            await _tick()
    if word:
        yield word


async def _tick() -> None:
    import asyncio

    await asyncio.sleep(0.02)


async def stream_diagnosis(state: dict) -> AsyncIterator[str]:
    if os.environ.get("OPENAI_API_KEY"):
        async for token in _openai(state):
            yield token
        return
    if os.environ.get("GEMINI_API_KEY"):
        async for token in _gemini(state):
            yield token
        return
    async for token in stream_text(_local_diagnosis(state)):
        yield token


async def _openai(state: dict) -> AsyncIterator[str]:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"], base_url=os.environ.get("OPENAI_BASE_URL"))
    stream = await client.chat.completions.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
        stream=True,
        messages=[
            {"role": "system", "content": state.get("skill_instructions") or "You debug Java from captured JDWP locals."},
            {"role": "user", "content": _local_diagnosis(state)},
        ],
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content or ""
        if delta:
            yield delta


async def _gemini(state: dict) -> AsyncIterator[str]:
    from google import genai

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    stream = await client.aio.models.generate_content_stream(
        model=os.environ.get("GEMINI_MODEL", "gemini-2.0-flash"),
        contents=_local_diagnosis(state),
    )
    async for chunk in stream:
        text = getattr(chunk, "text", "") or ""
        if text:
            yield text
