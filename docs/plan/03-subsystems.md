# 03 — Subsystem Deep-Dives

## 3.1 Orchestrator (Responses API loop)
**Plan-then-Execute:** the model first plans which tools to call, *then* untrusted content is processed —
so an injected instruction in a PDF can change draft *content* but not *which actions run*.
`parallel_tool_calls=False` for any mutating tool (so each is interceptable); parallel allowed for
read-only fan-out.

Loop: `function_call` → (read/draft: execute via `Tool.run`; publish: bubble up `ProposedAction`) →
append `function_call_output` → repeat until prose answer. Chain with `previous_response_id` to avoid
resending full history. Stream typed SSE events:
- `response.output_item.added` (function_call) → emit `tool_started` ("Calling create_quiz…")
- `response.function_call_arguments.delta/done` → buffer args, then execute
- `response.output_text.delta` → `assistant_delta`
- `response.completed` → `done`

## 3.2 Memory (two channels)
- **Transcript:** recent N turns verbatim + a running summary of older turns; compaction triggered on a
  token threshold; condense stale tool-output dumps early.
- **Artifact registry:** `{art_id → {type, title, status, version, provenance, payload}}` for
  `uploaded_file | assessment_draft | announcement_draft | lecture_draft`. Mutations ("add 5 more",
  "make harder") are **operations that bump a version** — never appended as prose. The draft therefore
  **survives compaction** because it lives in structured state, not chat history.
- **Reference resolution:** a **focus stack** (recency + type). "it/that quiz" resolves against the
  registry; a compact **artifact manifest** (IDs + titles + status) is injected each turn; vague commands
  are rewritten into ID-scoped operations; **ambiguity → confirm** ("Editing 'Ch3 Quiz' (12 Qs)?").
- IDs are namespaced by `tenant/course/user` now, so **cross-session memory can be added later** without rework.
- Pitfalls to avoid: conflating working vs long-term memory; storing artifacts only in chat history;
  naive full-context accumulation ("context rot"); over-aggressive compaction; guessing ambiguous references.

## 3.3 Quiz generation pipeline (the product differentiator)
1. **Ingest → chunk → retrieve (RAG):** generate strictly from retrieved spans; **store the source span as
   a citation on every question** ("view source"; reduces hallucination).
2. **Generate (PS4 prompt):** Chain-of-Thought + explicit **Bloom-level definitions** + **1–2 few-shot
   exemplars per level**; persona "graduate-level instructor"; temp ≈ 0.9. **Don't over-stuff** the prompt
   (extra instructions degraded quality in studies, esp. smaller models).
3. **Type-specific strict structured output** per type (maps to mooKIT): `mcq_single` (exactly-one-correct),
   `mcq_multi` (≥1 correct), `true_false`, `fib` (answer key + accepted variants / numeric range),
   `descriptive` (auto-generated **rubric**).
4. **Distractors:** encode anticipated **misconceptions** (not "wrong-but-related"); run a quality check
   (flag implausible/overlapping/"all/none of the above").
5. **Verify:** rule-based + LLM critique screening 4 hallucination types — **reasoning inconsistency,
   insolvability, factual error, math error**; auto-flag/regenerate. **LLM critique flags for the human; it
   is never the final judge** (LLM evaluators misalign with experts).
6. **Knobs:** Bloom level, difficulty (multi-tier), reading level, count, type-mix.
7. **Editable preview → commit** maps to mooKIT: `POST /assessments/{type}` (draft) → sections → questions
   → publish via `PUT ...published.status=1`. Bulk question creation = ARQ job with progress.

> Known weakness: LLMs are strong at lower-order Bloom (Remember/Understand/Apply) but weaker on
> higher-order (Analyze/Create) — ~65% skill alignment. **Route higher-order + high-stakes questions to
> mandatory human review.**

## 3.4 Security architecture (defense in depth)
The honest baseline: input-level defenses (spotlighting, classifiers) are *probabilistic and individually
bypassable*. The **load-bearing controls are architectural isolation + the deterministic confirmation gate.**
1. **Architectural isolation:** Plan-then-Execute; untrusted doc/API text processed by a quarantined step
   that emits only structured fields, never tool calls.
2. **Confirmation gate:** publish/send executed only by non-LLM code, behind a **one-time token bound to
   `(action, targetId, content-hash)`** — re-drafting voids the token (prevents "approve benign, swap
   malicious"); preview renders the *actual* payload (resolved recipients, exact text).
3. **Tool-arg allow-listing:** recipients/audience/targets resolved **server-side** from the session — the
   model/document can never name a recipient; every call permission-checked in code against
   `GET /user_permissions/allowed`.
4. **Spotlighting:** all untrusted content wrapped in randomized delimiters labeled as data.
5. **Guardrails:** injection/jailbreak + moderation on uploaded text and tool outputs *before* context;
   block model-generated outbound links/markdown images (kills exfil channel).
6. **File safety:** magic-byte + container validation (not extension/MIME), size/page/zip-bomb limits, AV
   scan, sandboxed network-isolated extraction, strip active content, store outside web root.
7. **Multi-tenant:** `tenant_key` on every row + query; tenant-prefixed cache keys; per-tenant scoped
   logs/traces; tenant derived from session only. (RLS `FORCE` as a safety net; mind PgBouncer
   transaction-pooling — use `SET LOCAL`.)
8. **Instruction hierarchy:** immutable rules in system message; no secrets in prompt (avoid system-prompt leakage).

Maps to **OWASP LLM Top-10 (2025):** LLM01 Prompt Injection (incl. indirect), LLM06 Excessive Agency,
LLM05 Improper Output Handling, LLM02 Sensitive Info Disclosure, LLM07 System-Prompt Leakage, LLM08
Vector/Embedding Weaknesses.

## 3.5 Infrastructure & ops
- **SSE backplane via Redis pub/sub** so any pod serves any stream → **no sticky sessions** (preserves
  autoscaling). Heartbeat keeps proxies from idling out the connection; abort on client disconnect.
- **ARQ workers** scale independently of API pods; progress written to Redis → surfaced as `tool_progress`.
- **Resilience:** explicit per-call timeouts (long `read` for streams, short connect/pool); `tenacity`
  retries on 429/5xx + jitter, honor `Retry-After`, idempotency keys on POSTs; per-dependency circuit
  breakers; provider/model fallback chain; Redis-backed per-tenant rate limiting.
- **Observability:** OTel GenAI conventions (experimental — wrapped) + Langfuse traces; per-tenant
  token/cost dashboards; correlation `request_id` propagated through SSE + ARQ.
- **Audit log:** append-only `{instanceId,userId,sessionId,prompt,action,tool,status,timestamp}` with
  provenance ("AI-generated · edited by instructor"); kept separate from observability traces.
- **Deploy:** stateless containers, HPA on CPU/active-connections, liveness/readiness/startup probes,
  graceful SIGTERM drain for in-flight streams/jobs. CPU instance — no GPU.
