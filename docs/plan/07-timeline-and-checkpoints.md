# 07 — Parallel Timeline & Integration Checkpoints

Both developers work in parallel against the frozen [shared contracts](05-shared-contracts.md). The two
tracks meet only at the six checkpoints (CP1–CP6). See [dev-a-workplan.md](dev-a-workplan.md) and
[dev-b-workplan.md](dev-b-workplan.md) for the task-level detail.

| Phase | Dev A (Platform / Integration / Security) | Dev B (AI Brain / Domain) | Checkpoint |
|---|---|---|---|
| **P0 Foundations** | App skeleton, config, `MooKitClient` (read) + `FakeMooKitClient`, tenant schema, in-memory stores, **freeze contracts** | `LLMProvider` (Responses API, streaming), bare orchestrator loop, prompt-cache discipline, `EchoTool` | **CP1** — contracts frozen; hello-world chat turn streams end-to-end |
| **P1 Core loop** | SSE layer + event schema, `RequestContext`, auth/permissions, Redis stores, audit, ARQ scaffolding | Orchestrator + tool dispatch, two-channel memory, reference resolver, tool registry, `common` tools | **CP2** — multi-turn chat with a read-only tool; artifacts tracked; tenant isolation tested |
| **P2 Files + Quiz** | Upload API, magic-byte validation, **sandboxed extraction**, RAG index + `retrieve()` | RAG-grounded quiz pipeline: PS4 prompting, per-type schemas, distractors, verification, rubric | **CP3** — PDF → grounded, cited, verified, editable quiz draft (all 5 types) |
| **P3 Confirm + 3 modules** | **Confirmation gate** (tokens, content-hash, executor), mooKIT write helpers, bulk-question ARQ job | Assessment/announcement/lecture tools, `ProposedAction` + faithful `PreviewRender`, provenance | **CP4** — all three flows publish to mooKIT **only** after confirm |
| **P4 Hardening** | Isolation tests, guardrail hooks, resilience (retries/breakers/rate-limit), observability, deploy | Spotlighting + guardrails, eval harness (quality / hallucination / injection red-team), prompt tuning | **CP5** — security review + load test + isolation + evals green |
| **P5 Deliverables** | Deployment guide, service API docs, infra runbook, sample-UI wiring | Architecture doc (AI), demo script, editable quiz-preview UI, eval report | **CP6** — working demos of all three flows + complete docs |

## Checkpoint exit criteria (definition of "integrated")
- **CP1:** The 7 contracts are merged and immutable; `POST /v1/chat` streams `assistant_delta` from Dev B's
  loop through Dev A's SSE layer; `MooKitClient.get_permissions` works against the live test instance.
- **CP2:** A read-only tool round-trips through orchestrator → `MooKitClient`; "make that one harder"
  resolves to the correct artifact; two tenants cannot see each other's sessions/artifacts.
- **CP3:** Real PDF → validated, sandboxed-extracted, chunked, retrievable; quiz pipeline produces a draft
  where every question cites a source span; oversized/corrupt/zip-bomb files rejected cleanly.
- **CP4:** Quiz, announcement, and lecture each go draft → preview → confirm → live mooKIT object; rejecting
  discards; editing after approval invalidates the token; **no write endpoint reachable without confirm**.
- **CP5:** Cross-tenant access tests fail closed; injection red-team yields zero unconfirmed actions;
  retries/breakers/rate-limits in place; per-tenant cost dashboard live; load test sustains concurrent
  multi-instance traffic.
- **CP6:** Demos run for all three flows; architecture/API/deployment/setup docs complete.

## Sequencing notes
- **P0 contract-freeze is the critical path.** Nothing parallelizes safely until CP1.
- Dev B is unblocked from real infra by `FakeMooKitClient` + in-memory stores (shipped at CP1).
- Dev A is unblocked from the AI brain by `EchoTool` + a minimal `LLMProvider` (shipped at CP1).
- The **confirmation gate (P3)** is the one place both tracks tightly interlock — schedule a joint
  working session at the P2→P3 boundary to align `ProposedAction` ⇄ executor.
