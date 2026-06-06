# AI Architecture (Dev B) — mooKIT AI Assistant

How the AI brain works, end to end. Companion to the plan docs in `docs/plan/`.

## 1. Request lifecycle (a chat turn)

```
user_text ─► Orchestrator.run_turn(ctx, user_text)
   │  append user msg → maybe_compact transcript
   │  manifest = ReferenceResolver.manifest(ctx)         (artifact channel)
   │  transcript = TranscriptManager.view(ctx)           (transcript channel)
   │  input = build_input(manifest, transcript, user_turn)   (variable content last)
   ▼
LLMProvider.respond(instructions=SYSTEM_PROMPT, tools=registry.openai_tools(perms),
                    parallel_tool_calls=False if any mutating tool visible, prompt_cache_key=...)
   │  stream → LLMEvent: assistant_delta | tool_call_* | response_completed
   ▼
on tool_call_args_done:
   read/draft  → Tool.run → ToolResult → screen output (guardrails) → function_call_output → loop
   publish     → Tool.run → ProposedAction → emit pending_confirmation → STOP (human confirms)
   ▼
prose with no tool calls → emit done; persist assistant msg
```

The loop chains with `previous_response_id` so history isn't resent. Events map 1:1 to the SSE schema
(Contract 6): `assistant_delta`, `tool_started`, `tool_progress`, `artifact_updated`,
`pending_confirmation`, `error`, `done`.

## 2. Plan-then-Execute + the confirmation gate (security spine)

- **Architectural isolation.** The model decides *which* tools to call before untrusted document/API
  text enters the reasoning channel. Untrusted text shapes *content*, never *control flow*.
- **Publish tools only propose.** `publish_assessment` / `send_announcement` / `publish_lecture` return
  a `ProposedAction` (action + exact mooKIT payload + faithful `PreviewRender` + `content_hash`). They
  physically never call a mooKIT write. Only Dev A's deterministic gate executes the write, behind a
  one-time token bound to `(action, target, content_hash)` — re-drafting changes the hash and voids the
  token (prevents "approve benign, swap malicious"). Proven by `tests/test_cp4_flows.py` and
  `app/evals/injection_redteam.py` (`unconfirmed_actions == 0`).
- **Server-side targets.** Tools accept *intent* ("all students", "Week 4"), never resolved recipient
  IDs from model/document text.
- **Hygiene layers:** spotlighting (`app/core/prompts/spotlight.py`), guardrail screening of tool
  outputs (`app/core/guardrails.py`), strict Structured Outputs, markdown sanitization (anti-exfil).

## 3. Two-channel memory (`app/core/memory.py`)

- **Transcript channel:** recent N turns verbatim + a running summary; compaction on a token threshold;
  stale tool dumps condensed first.
- **Artifact channel:** typed, versioned objects (`ArtifactRegistry`). Mutations ("add 5 more", "make
  harder") are **operations that bump `version`**, never appended as prose — so a draft **survives
  compaction**. `ReferenceResolver` injects a recent-first manifest each turn and resolves "it/that
  quiz" by recency × type; ambiguity ⇒ confirm.

## 4. Quiz pipeline (`app/gen/quiz/`) — the differentiator

```
retrieve spans (rag) → generate per type+Bloom (PS4 prompting, strict schema)
  → OVERRIDE citation with server-chosen span (grounding not trusted from the model)
  → distractor quality check (mcq) → attach rubric (descriptive) → verify (4 hallucination classes)
  → assemble assessment_draft (provenance + per-question citation + flags)
```

- **Per-type schemas** (`schemas.py`) validate mooKIT invariants (mcq_single = exactly one correct;
  fib = discrete XOR numeric range; etc.) and emit `to_mookit_payload()`.
- **Verification** (`verify.py`) flags reasoning_inconsistency / insolvability / factual_error /
  math_error; LLM critique is a *flagger*, never a judge. Higher-order Bloom → `higher_order_review`.
- **Knobs** (`params.py`): Bloom, difficulty, reading level, count, type-mix — conversationally
  adjustable via versioned edits.
- All LLM touchpoints are injected seams (`QuestionGenerator`, `RubricGenerator`, `CritiqueFn`) so the
  whole pipeline is deterministically testable offline; `OpenAIQuestionGenerator` is the live path.

## 5. The seams (how Dev B stays decoupled from Dev A)

Everything is typed against `app/contracts/` (the 7 interfaces). Dev B runs fully solo against the
fakes in `tests/fakes/` (`FakeMooKitClient`, in-memory stores, fake `retrieve`, `ConfirmHarness`). When
Dev A's real infra lands it swaps at the DI boundary with no orchestrator/tool changes.

## 6. OWASP LLM Top-10 mapping
LLM01 Prompt Injection → Plan-then-Execute + gate + spotlighting; LLM06 Excessive Agency → publish
tools only propose; LLM05 Improper Output Handling → markdown sanitization; LLM02/LLM07 Sensitive
Info / System-Prompt Leakage → no secrets in prompt, instruction hierarchy; LLM08 Vector/Embedding →
tenant-scoped retrieval (Dev A).
