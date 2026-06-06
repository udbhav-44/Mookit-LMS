"""Orchestrator (Plan-then-Execute loop) — Dev B, integrated onto Dev A's platform contracts.

Drives a turn:
  1. Assemble instructions (system) + tool schemas + input (manifest → transcript → user turn).
  2. Stream the model (canonical generic LLMEvent) with parallel_tool_calls=False when a mutating tool
     is visible.
  3. On a completed tool call:
       - read/draft tier  → execute via Tool.run, append function_call_output, continue the loop.
       - publish tier     → DO NOT execute. Persist the ProposedAction via the confirmation gate seam
                            and surface `pending_confirmation`; the deterministic executor runs it later.
  4. Loop with previous_response_id chaining until prose with no tool calls; emit done.

`run_turn` yields typed `OrchestratorEvent`s (used by tests). `stream` adapts them to the SSE dict shape
`{"event","data": json}` that Dev A's app/api/chat.py forwards to the client.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel

from app.config import Settings, get_settings
from app.contracts import (
    ArtifactRegistry,
    LLMProvider,
    MooKitClient,
    ProposedAction,
    RequestContext,
    SessionStore,
    ToolResult,
)
from app.core.guardrails import screen_input, screen_tool_output
from app.core.memory import TranscriptManager
from app.core.prompts import SYSTEM_PROMPT, build_input
from app.core.prompts.assembly import prompt_cache_key
from app.core.reference_resolver import ReferenceResolver
from app.preview.render import preview_from_artifact
from app.tools.registry import ToolRegistry, UnknownToolError

MAX_TOOL_ROUNDS = 8  # safety bound on the plan-execute loop

# Persists a ProposedAction and returns (action_id, confirm_token). In the app this is
# ConfirmationGate.propose; in tests a fake. None → emit a token-less pending_confirmation.
ProposalSink = Callable[[RequestContext, ProposedAction], Awaitable[tuple[str, str]]]


class OrchestratorEvent(BaseModel):
    """Maps to the SSE wire schema (Contract 6)."""

    event: Literal[
        "assistant_delta",
        "tool_started",
        "tool_progress",
        "artifact_updated",
        "pending_confirmation",
        "error",
        "done",
    ]
    data: dict[str, Any]


class Orchestrator:
    def __init__(
        self,
        *,
        llm: LLMProvider,
        registry: ToolRegistry,
        sessions: SessionStore,
        artifacts: ArtifactRegistry,
        resolver: ReferenceResolver,
        mookit: MooKitClient,
        settings: Settings | None = None,
        guardrail_hook: Any | None = None,
        proposal_sink: ProposalSink | None = None,
    ) -> None:
        self._llm = llm
        self._registry = registry
        self._sessions = sessions
        self._artifacts = artifacts
        self._resolver = resolver
        self._mookit = mookit
        self._guardrail_hook = guardrail_hook
        self._proposal_sink = proposal_sink
        self._settings = settings or get_settings()
        self._transcript = TranscriptManager(
            sessions,
            max_tokens=self._settings.memory.transcript_max_tokens,
            keep_recent=self._settings.memory.transcript_keep_recent,
        )

    # ------------------------------------------------------------------
    # SSE adapter consumed by app/api/chat.py
    # ------------------------------------------------------------------
    async def stream(self, ctx: RequestContext, user_text: str) -> AsyncIterator[dict[str, str]]:
        async for ev in self.run_turn(ctx, user_text):
            yield {"event": ev.event, "data": json.dumps(ev.data)}

    async def run_turn(
        self, ctx: RequestContext, user_text: str
    ) -> AsyncIterator[OrchestratorEvent]:
        # Guardrail screen on the user input. A blocking hook (e.g. moderation) stops the turn;
        # flags-only results are advisory (the confirmation gate remains the real backstop).
        gr = await screen_input(user_text, hook=self._guardrail_hook)
        if gr.blocked:
            yield OrchestratorEvent(
                event="error",
                data={"code": "input_blocked", "message": "Input flagged by content moderation.",
                      "retryable": False, "flags": gr.flags},
            )
            yield OrchestratorEvent(event="done", data={"response_id": ""})
            return

        await self._sessions.append_message(ctx, "user", user_text)
        await self._transcript.maybe_compact(ctx)

        tools = self._registry.openai_tools(ctx.permissions)
        parallel = not self._registry.has_mutating_tool(ctx.permissions)
        cache_key = prompt_cache_key(tenant_key=ctx.tenant_key, model=self._settings.openai.model)

        manifest = await self._resolver.manifest(ctx)
        transcript = await self._transcript.view(ctx)
        input_items: list[dict[str, Any]] = build_input(
            manifest=manifest, transcript=transcript, user_turn=user_text
        )

        previous_response_id: str | None = None

        for _round in range(MAX_TOOL_ROUNDS):
            pending_tool_calls: list[dict[str, Any]] = []  # each: {call_id, name, arguments}
            round_text: list[str] = []
            response_id: str | None = None
            errored = False

            stream = self._llm.respond(
                instructions=SYSTEM_PROMPT,
                input=input_items,
                tools=tools,
                tool_choice="auto",
                parallel_tool_calls=parallel,
                previous_response_id=previous_response_id,
                prompt_cache_key=cache_key,
            )

            async for ev in stream:
                etype = ev.event_type
                data = ev.data if isinstance(ev.data, dict) else {}
                if etype == "assistant_delta":
                    text = data.get("text", "")
                    round_text.append(text)
                    yield OrchestratorEvent(event="assistant_delta", data={"text": text})
                elif etype == "tool_call_started":
                    yield OrchestratorEvent(
                        event="tool_started",
                        data={"tool": data.get("name", ""), "label": f"Calling {data.get('name', '')}…"},
                    )
                elif etype == "tool_call_args_done":
                    pending_tool_calls.append(data)
                elif etype == "response_completed":
                    response_id = data.get("response_id")
                elif etype == "error":
                    errored = True
                    yield OrchestratorEvent(
                        event="error",
                        data={
                            "code": data.get("code", "error"),
                            "message": data.get("message", ""),
                            "retryable": data.get("retryable", False),
                        },
                    )

            previous_response_id = response_id

            if errored:
                return

            if not pending_tool_calls:
                if round_text:
                    await self._sessions.append_message(ctx, "assistant", "".join(round_text))
                yield OrchestratorEvent(event="done", data={"response_id": response_id or ""})
                return

            input_items = []
            proposed = False
            for call in pending_tool_calls:
                outcome = await self._dispatch(ctx, call)
                for emitted in outcome.events:
                    yield emitted
                if outcome.proposed:
                    proposed = True
                if outcome.function_output is not None:
                    input_items.append(outcome.function_output)

            if proposed:
                yield OrchestratorEvent(event="done", data={"response_id": response_id or ""})
                return

        yield OrchestratorEvent(
            event="error",
            data={"code": "max_rounds", "message": "tool loop exceeded bound", "retryable": False},
        )

    async def _dispatch(self, ctx: RequestContext, call: dict[str, Any]) -> _Dispatch:
        call_id = call.get("call_id", "")
        name = call.get("name", "")
        arguments = call.get("arguments", {}) or {}
        events: list[OrchestratorEvent] = []
        try:
            tool = self._registry.get(name)
        except UnknownToolError:
            return _Dispatch(
                events=[
                    OrchestratorEvent(
                        event="error",
                        data={"code": "unknown_tool", "message": f"unknown tool: {name}", "retryable": False},
                    )
                ],
                function_output=_fn_output(call_id, {"ok": False, "error": "unknown_tool"}),
                proposed=False,
            )

        result = await tool.run(ctx, arguments)

        if isinstance(result, ProposedAction):
            # Publish tier: NEVER execute. Persist via the gate seam, surface for confirmation.
            data: dict[str, Any] = {
                "action": result.action,
                "target_ref": result.target_ref,
                "content_hash": result.content_hash,
                "preview": result.preview.model_dump(),
            }
            if self._proposal_sink is not None:
                action_id, confirm_token = await self._proposal_sink(ctx, result)
                ttl = self._settings.security.confirm_token_ttl_seconds
                data["action_id"] = action_id
                data["confirm_token"] = confirm_token
                data["expires_at"] = (
                    datetime.now(timezone.utc) + timedelta(seconds=ttl)
                ).isoformat()
            events.append(OrchestratorEvent(event="pending_confirmation", data=data))
            return _Dispatch(events=events, function_output=None, proposed=True)

        # read/draft tier: feed the result back to the model.
        if isinstance(result, ToolResult) and result.artifact_id:
            art = await self._artifacts.get(ctx, result.artifact_id)
            if art is not None:
                data: dict[str, Any] = {
                    "artifact_id": art.id,
                    "type": art.type,
                    "version": art.version,
                }
                preview = preview_from_artifact(art)
                if preview is not None:
                    data["preview"] = preview.model_dump()
                if art.type.endswith("_draft"):
                    data["payload"] = art.payload
                events.append(OrchestratorEvent(event="artifact_updated", data=data))
        payload = _tool_result_payload(result)
        flags = await self._screen_output(payload)
        if flags:
            payload["_guardrail_flags"] = flags
        return _Dispatch(events=events, function_output=_fn_output(call_id, payload), proposed=False)

    async def _screen_output(self, payload: dict[str, Any]) -> list[str]:
        text = json.dumps(payload, ensure_ascii=False)
        result = await screen_tool_output(text, hook=self._guardrail_hook)
        return result.flags


class _Dispatch:
    def __init__(
        self,
        *,
        events: list[OrchestratorEvent],
        function_output: dict[str, Any] | None,
        proposed: bool,
    ) -> None:
        self.events = events
        self.function_output = function_output
        self.proposed = proposed


def _tool_result_payload(result: ToolResult) -> dict[str, Any]:
    return {
        "ok": result.ok,
        "data": result.data,
        "artifact_id": result.artifact_id,
        "message": result.message,
        "error": result.error.model_dump() if result.error else None,
    }


def _fn_output(call_id: str, output: dict[str, Any]) -> dict[str, Any]:
    return {"type": "function_call_output", "call_id": call_id, "output": json.dumps(output)}
