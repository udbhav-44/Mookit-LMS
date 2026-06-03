# 10 — Research Synthesis & References (2025–2026)

This plan is grounded in parallel research across five areas. Below is the actionable synthesis plus
primary sources. **Caveat:** vendor performance/benchmark numbers (cache %, latency, accuracy) are largely
self-reported — treated as directional; architectural patterns and primary-source guidance are well-corroborated.

---

## A. OpenAI agent API patterns
- **Use the Responses API** for a new 2026 backend. **Assistants API is deprecated (announced Aug 26 2025),
  sunsets Aug 26 2026** — do not build on it. Chat Completions still works but is "not recommended for new projects."
- **Structured Outputs (strict JSON Schema)** via `responses.parse` + Pydantic — constrained decoding makes
  conformance a hard guarantee. Strict-mode rules: all properties `required`, `additionalProperties:false`,
  optionals as `["type","null"]`, recursion via `$ref:"#"`. Handle refusals + length truncation explicitly.
- **Tool calling:** `tool_choice` ∈ auto/required/none/specific; `parallel_tool_calls=False` to make each
  mutating call interceptable (HITL). `allowed_tools` keeps the full tool list cacheable.
- **Streaming:** typed semantic SSE events (`output_item.added`, `function_call_arguments.delta/done`,
  `output_text.delta`, `completed`). Tool execution itself isn't streamed — emit your own progress events.
- **Cost/latency:** automatic prompt caching (≥1024-token prefix, 128-token increments) — keep system
  prompt + tool schemas byte-stable and first; set `prompt_cache_key`. Chain with `previous_response_id`.
- **Framework:** OpenAI Agents SDK has built-in HITL approvals (maps to our confirm gate); a hand-rolled
  Responses loop gives max control + provider portability. We chose the hand-rolled loop behind an
  `LLMProvider` ABC.

Sources: developers.openai.com (migrate-to-responses, structured-outputs, function-calling, streaming-responses,
prompt-caching); community.openai.com (Assistants deprecation); openai.github.io/openai-agents-python (HITL).

## B. Agent memory & context management
- **Two channels:** transcript (buffer + summary hybrid; compact on token threshold; keep recent N verbatim)
  vs **artifact registry** (structured objects with stable IDs, version, provenance — survive compaction).
- **Reference resolution = recency + type matching** against a focus stack, not coreference NLP; inject an
  artifact manifest each turn; rewrite vague commands to ID-scoped ops; confirm on ambiguity.
- **No memory framework needed for session-scoped design** — a Redis session store suffices. Mem0/Letta/
  Zep/LangMem are long-term/cross-session layers; keep the store interface abstract + IDs namespaced to add
  them later. (LangChain's `ConversationBufferMemory` is deprecated → LangGraph checkpointers.)

Sources: anthropic.com/engineering/effective-context-engineering-for-ai-agents; platform.claude.com (compaction);
mem0.ai (working memory); Google ADK blog; agentmarketcap.ai (memory vendor landscape 2026).

## C. Prompt-injection & agent security
- **The boundary is architecture, not the model.** Input filters (spotlighting, classifiers, instruction
  hierarchy) are probabilistic and individually bypassable.
- **Load-bearing controls:** (1) architectural isolation — Plan-then-Execute / Dual-LLM (CaMeL) so untrusted
  content can't select actions; (2) deterministic HITL gate — publish executed by non-LLM code behind a
  one-time token bound to (action, target, content-hash) with a faithful rendered preview; (3) tool-arg
  allow-listing — targets/recipients resolved server-side, never from model/doc text.
- **Hygiene layers:** spotlighting/datamarking untrusted content; OpenAI Guardrails (injection/jailbreak +
  tool guardrails) + Moderation; structured outputs to shrink the injection surface; block model-generated
  outbound links/markdown images (anti-exfil); instruction hierarchy (system > developer > user > tool).
- **File upload:** magic-byte + container validation (not extension/MIME); size/page/zip-bomb limits; AV
  scan; sandboxed network-isolated extraction; strip active content; store outside web root.
- **Multi-tenant:** authz at retrieval (and every graph hop); tenant-keyed caches/logs/traces; tenant id
  from session only.

Sources: OWASP GenAI LLM Top-10 (2025); arXiv 2506.08837 (Design Patterns for Securing LLM Agents);
Microsoft MSRC (indirect prompt injection); arXiv 2403.14720 (Spotlighting); model-spec.openai.com
(Instruction Hierarchy); guardrails.openai.com; OWASP file-upload & prompt-injection cheat sheets.

## D. Comparable LMS/instructor AI products
- **Khanmigo** (task-specific tools, Coeditor refine loop, one-click export), **Cogniti** (instructor-built
  agents on Azure OpenAI + RAG "onboarding package", full conversation visibility — closest analog),
  **Canvas IgniteAI** (draft/"foundation" framing, grounded in materials + standards, inline AI),
  **Blackboard/Anthology** (build a question bank from a doc, 10-tier complexity scale, Bloom alignment,
  edit-tracking metadata), **Copilot Teach** (draft→customize→distribute into Forms; reading-level/length/
  difficulty knobs), **Gemini in Classroom** (grade-level + objective inputs → Forms), **Quizizz/Wayground**
  (PDF/DOC/PPT/URL → quiz in seconds; "replace with similar", change type/tone/level; tagline
  *"We make suggestions. You make decisions."*).
- **Quiz generation best practice:** RAG grounding + per-question source citations; multi-stage verification
  (screen reasoning inconsistency / insolvability / factual / math errors); **PS4 prompting** (CoT + Bloom
  level defs + 1–2 few-shot per level — more instructions *hurt*); misconception-based distractors + quality
  check; per-type validation; rubric for descriptive; LLM critique as flagger, not judge; route higher-order
  Bloom to human review.
- **HITL UX:** generate→review→edit→approve, never auto-execute; confirmation scales with stakes; inline +
  conversational editing; provenance/edit-tracking; flag/feedback on every item.

Sources: khanmigo.ai/teachers; sydney.edu.au + educational-innovation.sydney.edu.au (Cogniti);
instructure.com (IgniteAI); help.anthology.com (AI Design Assistant); microsoft.com/education (Copilot Teach);
blog.google/education (Gemini); wayground.com/quizizz-ai; arXiv 2408.04394 (Bloom-level QG / PS4);
arXiv 2404.02124 (distractor generation); HITL UX (aufaitux.com, shapeof.ai); teacher-trust (Springer IJAIED).

## E. Multi-tenant FastAPI LLM service infra
- **FastAPI:** single shared `httpx.AsyncClient` via lifespan (explicit `Limits`/`Timeout`); `Annotated`+
  `Depends` DI; never block the event loop; `sse-starlette` v3.4.x with `ping` + `is_disconnected()`,
  DB session created inside the SSE generator.
- **Long tasks:** **ARQ + Redis** (asyncio-native, separate worker, persists/requeues, progress via Redis);
  Celery only if you already run it / need its maturity; `BackgroundTasks` only for short loss-tolerant work.
- **Tenancy:** shared-schema `tenant_id` (mandatory tenant-scoped queries) as default; RLS `FORCE` as safety
  net (mind PgBouncer transaction-pooling → `SET LOCAL`); tenant-prefixed cache keys; tenant-filtered RAG.
- **Observability:** OTel GenAI conventions (experimental — wrap them) + Langfuse / OpenLLMetry; per-tenant
  token/cost attribution; separate append-only audit log with request-id propagation.
- **Resilience:** explicit timeouts; `tenacity` retries (429/5xx + jitter, honor Retry-After); per-provider
  circuit breakers (pybreaker/pyresilience); provider/model fallback; Redis-backed per-tenant rate limiting.
- **Deploy:** stateless containers; HPA (CPU/active connections); **no sticky sessions** (Redis pub/sub
  backplane for SSE fan-out); liveness/readiness/startup probes; graceful SIGTERM drain; proxy buffering off
  + idle timeout > ping for SSE.

Sources: FastAPI lifespan/production guides; github.com/sysid/sse-starlette; ARQ vs Celery comparisons;
planetscale.com + aws.amazon.com (Postgres multi-tenancy / RLS); opentelemetry.io (GenAI observability);
signoz.io / helicone.ai (LLM observability); tenacity & pyresilience docs; Kubernetes HPA / sticky-session guidance.
