# 01 — Overview

## Objective
Build a **standalone AI Assistant microservice** that sits between mooKIT instances and an LLM provider.
mooKIT's frontend team builds the production chat UI; **we build the brain + a sample test UI**. The
service is reusable across multiple mooKIT deployments (e.g. `hello.iitk.ac.in`, `learn.online.iitk.ac.in`).

Phase-1 capabilities, all via natural-language chat with confirmation-before-publish:
1. **Assessment generation** from uploaded documents (PDF/DOCX/PPT/TXT/XLSX/CSV).
2. **Announcements** — draft and publish/email.
3. **Lecture publishing** — upload, schedule, publish under a week/module.

## Scope boundaries
- **In scope:** AI service, AI integration layer, file processing, session/context management, action
  execution, API layer, authentication mechanism, audit logging, sample test UI.
- **Out of scope:** production chat UI (mooKIT frontend team), and the underlying mooKIT REST APIs
  (provided by the mooKIT team — already live at `https://test.mookit.in/docs`).

## What changed from v1 (research-informed upgrades)
| Area | v1 | v2 (why) |
|---|---|---|
| OpenAI API | "Chat Completions / function-calling" | **Responses API** + **Structured Outputs (strict JSON Schema)**. Assistants API **sunsets Aug 26 2026** — avoid. Responses gives stateful chaining (`previous_response_id`) + better prompt-cache utilization. |
| Memory | "history + artifact store" | Formalized **two-channel memory**: transcript (buffer+summary compaction) vs **artifact registry** (structured, versioned, provenance) + a **focus stack** for reference resolution. The draft survives compaction because it lives in structured state, not chat history. |
| Quiz quality | "LLM generates questions" | **RAG-grounded generation with per-question source citations** + **multi-stage verification** (screens 4 hallucination types) + **PS4 prompting** (CoT + Bloom-level defs + few-shot) + **misconception-based distractors** with a quality check. |
| Security | "prompt-injection guards + confirmation" | **Architectural isolation** (Plan-then-Execute / quarantined extraction) so untrusted doc/API text *cannot select actions*; deterministic confirmation gate **outside the model loop** with **action+target+content-hash one-time tokens**; **server-side resolution of all recipients/targets**. |
| Long tasks | "Celery or BackgroundTasks" | **ARQ + Redis** (asyncio-native, matches FastAPI, separate worker, progress via Redis). |
| Infra | generic | `sse-starlette` w/ heartbeat, shared `httpx.AsyncClient` via lifespan, **shared-schema `tenant_id`** + RLS-as-safety-net, OTel GenAI + Langfuse, tenacity + circuit breakers + provider fallback, stateless + HPA + **no sticky sessions** (Redis pub/sub backplane). |

## Design principles (from the spec + comparable products)
- **Assist, don't replace** — the instructor is always the final decision-maker.
- **Never publish/send without explicit confirmation.** The confirmation gate is a hard, deterministic boundary.
- **Always preview before publishing**, showing the *actual* payload (rendered final artifact, resolved recipients).
- **Transparency / provenance** — log every action; mark generated content "AI-generated · edited by instructor".
- **Grounded + cited** — every quiz question carries a source-span citation ("view source").
- **Task-specific tools, not one open chatbot** — strongest products (Khanmigo, Copilot Teach) decompose into structured tools.
- **Output lands in the real workflow** — generation writes into actual mooKIT quiz/announcement/lecture objects.
- **Extensible** for future instructor workflows.

## Deliverables (per spec §22)
- Source code: AI Assistant Service + sample testing UI.
- Documentation: architecture doc, API documentation, deployment guide, setup instructions.
- Demonstration: working demos of assessment generation, announcement publishing, lecture publishing.
