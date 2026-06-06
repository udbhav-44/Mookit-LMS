"""B1.1 — Orchestrator (Plan-then-Execute loop).

Drives a turn:
  1. Assemble instructions (system) + tool schemas (stable prefix) and input (manifest → transcript →
     user turn) via build_input.
  2. Stream the model with parallel_tool_calls=False whenever a mutating tool is visible.
  3. On a completed tool call:
       - read/draft tier  → execute via Tool.run, append a function_call_output, continue the loop.
       - publish tier     → DO NOT execute. Surface the ProposedAction as a pending_confirmation and
                            stop that branch (the deterministic gate executes it, never the model).
  4. Loop with previous_response_id chaining until the model returns prose with no tool calls; emit done.

Emits OrchestratorEvent objects that map 1:1 to the SSE event schema (Contract 6).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Literal

from pydantic import BaseModel

from app.config import Settings, get_settings
from app.contracts.mookit import MooKitClient
from app.contracts.types import (
    ArtifactRegistry,
    AssistantDelta,
    ErrorEvent,
    LLMProvider,
    ProposedAction,
    RequestContext,
    ResponseCompleted,
    SessionStore,
    ToolCallArgsDone,
    ToolCallStarted,
    ToolResult,
)
from app.core.guardrails import screen_tool_output
from app.core.memory import TranscriptManager
from app.core.prompts import SYSTEM_PROMPT, build_input
from app.core.prompts.assembly import prompt_cache_key
from app.core.reference_resolver import ReferenceResolver
from app.tools.registry import ToolRegistry, UnknownToolError

MAX_TOOL_ROUNDS = 8  # safety bound on the plan-execute loop


class OrchestratorEvent(BaseModel):
    """Maps to the SSE wire schema."""

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
    ) -> None:
        self._llm = llm
        self._registry = registry
        self._sessions = sessions
        self._artifacts = artifacts
        self._resolver = resolver
        self._mookit = mookit
        self._guardrail_hook = guardrail_hook
        self._settings = settings or get_settings()
        self._transcript = TranscriptManager(
            sessions,
            max_tokens=self._settings.transcript_max_tokens,
            keep_recent=self._settings.transcript_keep_recent,
        )

    async def run_turn(
        self, ctx: RequestContext, user_text: str
    ) -> AsyncIterator[OrchestratorEvent]:
        await self._sessions.append_message(ctx, "user", user_text)
        await self._transcript.maybe_compact(ctx)

        tools = self._registry.openai_tools(ctx.permissions)
        parallel = not self._registry.has_mutating_tool(ctx.permissions)
        cache_key = prompt_cache_key(tenant_key=ctx.tenant_key, model=self._settings.default_model)

        manifest = await self._resolver.manifest(ctx)
        transcript = await self._transcript.view(ctx)
        input_items: list[dict[str, Any]] = build_input(
            manifest=manifest, transcript=transcript, user_turn=user_text
        )

        previous_response_id: str | None = None
        assistant_text_parts: list[str] = []

        for _round in range(MAX_TOOL_ROUNDS):
            pending_tool_calls: list[ToolCallArgsDone] = []
            round_text: list[str] = []
            response_id: str | None = None
            errored = False

            stream = self._llm.respond(
                instructions=SYSTEM_PROMPT,
                input=input_items if previous_response_id is None else _delta_input(input_items),
                tools=tools,
                tool_choice="auto",
                parallel_tool_calls=parallel,
                previous_response_id=previous_response_id,
                prompt_cache_key=cache_key,
            )

            async for ev in stream:
                if isinstance(ev, AssistantDelta):
                    round_text.append(ev.text)
                    yield OrchestratorEvent(event="assistant_delta", data={"text": ev.text})
                elif isinstance(ev, ToolCallStarted):
                    yield OrchestratorEvent(
                        event="tool_started", data={"tool": ev.name, "label": f"Calling {ev.name}…"}
                    )
                elif isinstance(ev, ToolCallArgsDone):
                    pending_tool_calls.append(ev)
                elif isinstance(ev, ResponseCompleted):
                    response_id = ev.response_id
                elif isinstance(ev, ErrorEvent):
                    errored = True
                    yield OrchestratorEvent(
                        event="error",
                        data={"code": ev.code, "message": ev.message, "retryable": ev.retryable},
                    )

            assistant_text_parts.extend(round_text)
            previous_response_id = response_id

            if errored:
                return

            # No tool calls ⇒ the model produced a final prose answer.
            if not pending_tool_calls:
                if round_text:
                    await self._sessions.append_message(ctx, "assistant", "".join(round_text))
                yield OrchestratorEvent(event="done", data={"response_id": response_id or ""})
                return

            # Dispatch tool calls. After a publish proposal we stop (human must confirm).
            input_items = []
            proposed = False
            for call in pending_tool_calls:
                outcome = await self._dispatch(ctx, call)
                async for emitted in outcome.events:
                    yield emitted
                if outcome.proposed:
                    proposed = True
                if outcome.function_output is not None:
                    input_items.append(outcome.function_output)

            if proposed:
                # A publish-tier tool proposed an action; await human confirmation.
                yield OrchestratorEvent(event="done", data={"response_id": response_id or ""})
                return

        # Hit the loop bound.
        yield OrchestratorEvent(
            event="error",
            data={"code": "max_rounds", "message": "tool loop exceeded bound", "retryable": False},
        )

    async def _dispatch(self, ctx: RequestContext, call: ToolCallArgsDone) -> _Dispatch:
        events: list[OrchestratorEvent] = []
        try:
            tool = self._registry.get(call.name)
        except UnknownToolError:
            return _Dispatch(
                events=_aiter(
                    [
                        OrchestratorEvent(
                            event="error",
                            data={
                                "code": "unknown_tool",
                                "message": f"unknown tool: {call.name}",
                                "retryable": False,
                            },
                        )
                    ]
                ),
                function_output=_fn_output(call.call_id, {"ok": False, "error": "unknown_tool"}),
                proposed=False,
            )

        result = await tool.run(ctx, call.arguments)

        if isinstance(result, ProposedAction):
            # Publish tier: NEVER execute; surface for confirmation.
            events.append(
                OrchestratorEvent(
                    event="pending_confirmation",
                    data={
                        "action": result.action,
                        "target_ref": result.target_ref,
                        "content_hash": result.content_hash,
                        "preview": result.preview.model_dump(),
                    },
                )
            )
            return _Dispatch(events=_aiter(events), function_output=None, proposed=True)

        # read/draft tier: feed the result back to the model.
        if isinstance(result, ToolResult) and result.artifact_id:
            art = await self._artifacts.get(ctx, result.artifact_id)
            if art is not None:
                events.append(
                    OrchestratorEvent(
                        event="artifact_updated",
                        data={"artifact_id": art.id, "type": art.type, "version": art.version},
                    )
                )
        payload = _tool_result_payload(result)
        # Guardrails: screen the (possibly untrusted) tool output BEFORE it re-enters the model
        # context. We flag (not block) — the confirmation gate is the real backstop.
        flags = await self._screen_output(payload)
        if flags:
            payload["_guardrail_flags"] = flags
        return _Dispatch(
            events=_aiter(events),
            function_output=_fn_output(call.call_id, payload),
            proposed=False,
        )

    async def _screen_output(self, payload: dict[str, Any]) -> list[str]:
        import json

        text = json.dumps(payload, ensure_ascii=False)
        result = await screen_tool_output(text, hook=self._guardrail_hook)
        return result.flags


class _Dispatch:
    def __init__(
        self,
        *,
        events: AsyncIterator[OrchestratorEvent],
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
    import json

    return {"type": "function_call_output", "call_id": call_id, "output": json.dumps(output)}


def _delta_input(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """When chaining with previous_response_id, only the new function outputs / user turn are needed.

    The first round sends the full assembled input; subsequent rounds send only the delta items
    accumulated since (function_call_output entries).
    """
    return items


async def _aiter(items: list[OrchestratorEvent]) -> AsyncIterator[OrchestratorEvent]:
    for item in items:
        yield item
