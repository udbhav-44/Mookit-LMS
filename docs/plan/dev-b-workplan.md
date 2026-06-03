# Dev B — Work Plan: AI Brain & Domain Logic

**Role:** Owns the *intelligence + product* layer — the agent loop, memory, the three domain tool modules,
and the research-grade quiz-generation pipeline that makes this a product rather than a demo.

**Mental model:** Dev B can build and test the agent + quiz pipeline against a *fake `MooKitClient`* and an
*in-memory `SessionStore`* — zero dependency on real infra. Everything plugs into the seams in
[05-shared-contracts.md](05-shared-contracts.md).

**Owned packages**
```
app/llm/            base.py openai_provider.py events.py
app/core/           orchestrator.py memory.py reference_resolver.py prompts/
app/tools/          registry.py assessment.py announcement.py lecture.py common.py
app/gen/            quiz/  (rag.py prompting.py schemas.py verify.py distractors.py rubric.py)
app/gen/            announcement.py lecture_meta.py
app/preview/        render.py            (PreviewRender builders)
app/evals/          quiz_quality.py hallucination.py injection_redteam.py
sample-ui/          quiz-preview/  (the editable quiz preview component + provenance/flag UI)
```

---

## Cross-cutting principles Dev B must enforce everywhere
- **Untrusted content can never select actions.** Use **Plan-then-Execute**: the model decides *which*
  tools to call *before* untrusted doc/API text enters the reasoning channel. Untrusted text can shape
  *content*, never *control flow*.
- **Spotlighting:** wrap all document text + mooKIT-returned data in randomized, clearly-labeled
  delimiters and instruct the model it is **data, never instructions**.
- **Instruction hierarchy:** immutable safety rules live in the system message; no secrets in the prompt.
- **The model only proposes publishes.** Publish-tier tools return a `ProposedAction` (never call mooKIT
  writes themselves).
- **Ground everything.** Every quiz question carries a **source-span citation**. LLM self-critique
  *flags for the human* — it is never the final pedagogical judge.
- **`parallel_tool_calls=False` for mutating tools** so each is interceptable; parallel allowed for
  read-only fan-out.

---

## P0 — Foundations  → checkpoint **CP1**
Goal: bare Responses loop streams a token through Dev A's API layer; contracts frozen.

| # | Task | Detail |
|---|---|---|
| B0.1 | **Co-freeze contracts** | With Dev A, lock the 7 interfaces; agree the strict JSON-Schema dialect for tool params (all properties `required`, `additionalProperties:false`, optionals as `["type","null"]`). |
| B0.2 | `LLMProvider` (OpenAI) | Implement `respond()` on the **Responses API** with streaming; parse typed SSE events (`response.output_item.added`, `response.function_call_arguments.delta/done`, `response.output_text.delta`, `response.completed`) → our `LLMEvent` stream. Implement `respond_structured()` via `responses.parse` + Pydantic (strict). |
| B0.3 | Prompt-cache discipline | Keep system prompt + tool schemas **byte-stable and first** in the input; variable/user content last; set `prompt_cache_key`. Document the ordering rule. |
| B0.4 | `EchoTool` + system prompt skeleton | A read-tier tool + minimal system prompt so CP1 round-trips. |

**CP1 exit:** `respond()` streams `assistant_delta` events end-to-end through Dev A's SSE layer.

---

## P1 — Orchestrator + memory  → checkpoint **CP2**
Goal: real multi-turn chat, one read-only tool, artifacts tracked, references resolved.

| # | Task | Detail |
|---|---|---|
| B1.1 | **Orchestrator** | Plan-then-Execute loop: build `instructions` + spotlighted context + transcript + user turn → `respond(tools=…, parallel_tool_calls=False for mutating)`. Dispatch tool calls: read/draft → execute via `Tool.run`; publish → bubble up `ProposedAction`. Append `function_call_output`; loop until prose. Emit `tool_started`/`tool_progress` SSE events. Use `previous_response_id` chaining to avoid resending full history. |
| B1.2 | **Two-channel memory** | `app/core/memory.py`: (a) **transcript** = recent N turns verbatim + running summary; compaction triggered on a token threshold; condense stale tool-output dumps early. (b) **artifact registry** semantics: mutations ("add 5 more", "make harder") are **operations that bump `version`** on the structured object — never appended as prose. The draft thus survives compaction. |
| B1.3 | **Reference resolution** | `reference_resolver.py`: focus stack (recency + type). "it/that quiz" → resolve against registry; inject a compact **artifact manifest** (IDs + titles + status) into context each turn; rewrite vague commands into ID-scoped operations; **confirm on ambiguity** ("Editing 'Ch3 Quiz' (12 Qs) — add 5 more?"). |
| B1.4 | Tool registry | `registry.py`: register tools, expose OpenAI tool schemas, **filter by the user's permission matrix** so the model only sees allowed actions. |
| B1.5 | `common` tools | `users/me`, taxonomy lookup (resolve "Week 4"/"Module 2" → `weekId`/`topicId`), permission introspection — all read-tier, via `MooKitClient`. |

**CP2 exit:** multi-turn conversation; a read-only tool round-trips; "make that one harder" resolves to the right artifact; manifest injected each turn.

---

## P2 — Quiz generation pipeline (the differentiator)  → checkpoint **CP3**
Goal: a PDF → grounded, cited, verified, editable quiz draft covering all 5 question types.

| # | Task | Detail |
|---|---|---|
| B2.1 | **RAG-grounded generation** | `gen/quiz/rag.py`: pull relevant spans via Dev A's `retrieve()`; generate **strictly from retrieved evidence**; **store the source span/locator as a citation on every question** (powers "view source", reduces hallucination). |
| B2.2 | **PS4 prompting** | `gen/quiz/prompting.py`: Chain-of-Thought + explicit **Bloom-level definitions** + **1–2 few-shot exemplars per level**; persona = "graduate-level instructor"; temp ≈ 0.9 for diversity. **Do not over-stuff** the prompt (studies show extra instructions *degrade* quality, esp. on smaller models). |
| B2.3 | **Per-type structured schemas + validation** | `gen/quiz/schemas.py` (strict Structured Outputs) + validators, mapped to mooKIT question types: `mcq_single` (exactly one `isCorrect`), `mcq_multi` (≥1 correct), `true_false` (`trueFalseAnswer`), `fib` (discrete answers w/ accepted variants **or** numeric range), `descriptive` (free-form). |
| B2.4 | **Misconception distractors** | `gen/quiz/distractors.py`: generate distractors that encode *specific anticipated misconceptions* (not "wrong-but-related"); run a **distractor-quality check** flagging implausible/overlapping/"all/none of the above" filler. |
| B2.5 | **Multi-stage verification** | `gen/quiz/verify.py`: rule-based + LLM-critique screening the 4 hallucination types — **reasoning inconsistency, insolvability, factual error, math error**; auto-flag or regenerate failures. The critique **raises flags for the human**, never auto-approves. |
| B2.6 | **Rubric for descriptive** | `gen/quiz/rubric.py`: auto-generate a scoring rubric for descriptive questions. |
| B2.7 | Knobs | Expose **Bloom level, difficulty (multi-tier), reading level, count, type-mix** as generation parameters the instructor can set/adjust conversationally. |
| B2.8 | Draft artifact | Assemble into an `assessment_draft` artifact (with provenance `ai_generated=true`); enable conversational edits (add/remove/regenerate/change-type/change-difficulty) as versioned operations. |

**CP3 exit:** "Create a quiz from this PDF" → grounded draft, all 5 types valid, each question cites a source span, verification flags surfaced, knobs adjustable. (Route higher-order Bloom questions to mandatory human review — known ~65% alignment weakness.)

---

## P3 — Three modules + previews + commit  → checkpoint **CP4**
Goal: assessment, announcement, lecture each produce a faithful preview and commit via the confirm gate.

| # | Task | Detail |
|---|---|---|
| B3.1 | Assessment tools | draft/edit tools (read/draft tier) + `publish_assessment` (publish tier → `ProposedAction`). Map to mooKIT: create (draft) → sections → questions → publish. Build `PreviewRender` (per-question summary + warnings for higher-order items). |
| B3.2 | Announcement module | `gen/announcement.py`: draft `title`+`description`, infer `type` (normal/urgent) and `notifyMail` (email vs LMS), and **audience** (`sectionIds`; empty=all). `send_announcement` (publish tier) → `ProposedAction` with **audience chip** ("To: 142 students in CS101") + sanitized body in `PreviewRender`. **Recipients resolved server-side by Dev A — the model never names a recipient.** |
| B3.3 | Lecture module | `gen/lecture_meta.py`: resolve week/module via taxonomy; generate title (+ optional description). `publish_lecture` (publish tier) → `ProposedAction` with a **change-summary/diff** (title, module, visibility, attachments, schedule). Upload happens via Dev A's file path; attach video as course-resource. |
| B3.4 | Preview builders | `app/preview/render.py`: faithful renders for all three — show the *actual* payload, not a paraphrase. Sanitize markdown (no model-generated outbound links/images — anti-exfil). |
| B3.5 | Provenance | Stamp artifacts/commits "AI-generated · edited by instructor"; carry source citations through to the committed quiz. |

**CP4 exit:** all three flows: draft → faithful preview → (Dev A's) confirm → live mooKIT object; nothing sends/publishes on generation.

---

## P4 — Safety hardening + evals  → checkpoint **CP5**
Goal: the AI layer resists injection and the generation quality is measured, not assumed.

| # | Task | Detail |
|---|---|---|
| B4.1 | Spotlighting + hierarchy | Finalize delimiter/datamarking of all untrusted content; system-message safety policy; verify document-injected "publish/send now" instructions cannot trigger actions (the gate + server-side targets are the real backstop). |
| B4.2 | Guardrails integration | Use Dev A's guardrail hooks: injection/jailbreak + moderation on uploaded text and tool outputs *before* they enter context; structured outputs as an injection-surface reducer. |
| B4.3 | **Quiz-quality eval harness** | `evals/quiz_quality.py`: rubric scoring (understandability, relevance, grammar, clarity, answerability, Bloom alignment) on a fixed doc set; track regressions. Treat LLM evaluators as *flaggers* (they misalign with experts). |
| B4.4 | **Hallucination eval** | `evals/hallucination.py`: measure ungrounded claims / citation faithfulness against source spans. |
| B4.5 | **Injection red-team** | `evals/injection_redteam.py`: malicious-document and malicious-API-field test sets; assert no unconfirmed publish/send is ever reachable. |
| B4.6 | Prompt tuning | Iterate prompts against eval metrics; pin temperature/persona; document the prompt library. |

**CP5 exit:** eval suite runs in CI; injection red-team passes (zero unconfirmed actions); quiz-quality baseline recorded.

---

## P5 — Deliverables  → checkpoint **CP6**
| # | Task |
|---|---|
| B5.1 | **Architecture document** (AI side): orchestrator, memory model, quiz pipeline, prompt library, safety rationale. |
| B5.2 | **Demo script** for the three flows (quiz from PDF, announcement, lecture). |
| B5.3 | Sample-UI **editable quiz preview** component: per-question edit / regenerate / replace-with-similar / change type / change difficulty / **view source** / delete; provenance badge; flag/feedback control on every item; **audience-chip confirm dialog** for announcements; **diff view** for lecture publish. |
| B5.4 | Eval report (quality + hallucination + injection results). |

---

## Dev B acceptance checklist (definition of done)
- [ ] Plan-then-Execute: untrusted content can shape content but never control flow.
- [ ] All untrusted text spotlighted/delimited as data; safety rules in system message; no secrets in prompt.
- [ ] Publish-tier tools only ever return `ProposedAction` (never call mooKIT writes).
- [ ] Every quiz question carries a source-span citation; all 5 question types validate against mooKIT schemas.
- [ ] Misconception-based distractors + quality check; descriptive questions get a rubric.
- [ ] Multi-stage verification flags the 4 hallucination types; higher-order Bloom routed to human review.
- [ ] Two-channel memory: draft survives compaction; "it/that quiz" resolves correctly; ambiguity → confirm.
- [ ] `parallel_tool_calls=False` for mutating tools; structured outputs strict.
- [ ] Eval harness (quality + hallucination + injection) green in CI.
- [ ] Previews are faithful to the actual payload; sanitized (no model-generated outbound links/images).

## Key dependencies / handoffs
- **Needs from Dev A:** `RequestContext`, `MooKitClient` (+ `FakeMooKitClient`), `SessionStore`/`ArtifactRegistry`, RAG `retrieve()`, confirmation gate, guardrail hooks, SSE plumbing.
- **Gives to Dev A:** `LLMProvider` impl, `Tool` instances with correct risk tiers, `ProposedAction` + `PreviewRender`, prompt/safety policy, the quiz-preview UI component.
