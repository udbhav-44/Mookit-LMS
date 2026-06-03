# 08 — Open Questions & Risks

## Blockers / clarifications needed from the mooKIT team
1. **Source of truth for the API.** Confirm the live swagger (`https://test.mookit.in/docs`) is
   authoritative. The written spec §13 lists endpoints as "TBD," but the live OpenAPI is already populated
   with 55 endpoints — we are building against it.
2. **Production credential flow.** Confirm the frontend forwards `course` / `token` / `uid` per request
   (matches the dev static-header setup and the pass-through decision). Define how `instanceId` maps to a
   mooKIT base URL (the instance-registry format).
3. **Video path for lectures.** The API supports uploaded files (`/files/add`), Vimeo metadata
   (`/lectures/vimeo/{videoid}`), and resource URLs. Which is the intended path for lecture video?
4. **Taxonomy types per course.** Which `{type}` values represent weeks/modules/topics, so "Week 4"
   resolves reliably via `/taxonomies/{type}`?
5. **OpenAI account/key ownership + data residency.** Who owns the key; are there IITK data-residency or
   data-handling constraints that affect provider/region (or argue for an EU/India endpoint)?

## Resolved decisions (for reference)
- Stack: Python + FastAPI · LLM: OpenAI (Responses API, swappable) · Auth: pass-through ·
  Scope: all three modules in parallel · Infra: **CPU only, no GPU** (the g4dn.xlarge query is moot —
  no local model hosting; all inference is via OpenAI's API).

## Top risks & mitigations
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **Quiz quality on higher-order Bloom** (~65% alignment in studies) | High | Med | RAG grounding + per-question citations; multi-stage verification; route higher-order/high-stakes to mandatory human review |
| **Prompt injection** via uploaded docs / mooKIT-returned data | High | High | Architectural isolation (Plan-then-Execute) + deterministic confirmation gate + server-side target resolution are the real boundary; input filters are hygiene only |
| **mooKIT write-payload mismatches** (some fields inferred from `$ref`s) | Med | Med | P0/P3 contract tests against the live test instance before relying on writes |
| **Approval fatigue** (users rubber-stamp confirms) | Med | High | Risk-tiered gating (drafts free; only publish/send gated); faithful previews that make malicious actions visible; keep high-risk prompts rare |
| **Cross-tenant data leakage** (cache/log/RAG side channels) | Med | High | `tenant_key` on every row/key/log; tenant-filtered retrieval; RLS `FORCE` safety net; isolation red-team tests |
| **LLM cost / latency** at scale | Med | Med | Prompt caching (static-first), smaller models for routing/extraction, per-tenant cost dashboards + rate limits, `previous_response_id` chaining |
| **OpenAI Assistants API sunset (Aug 26 2026)** | — | — | Build on the **Responses API** from day one (already chosen) |
| **File-parser RCE / zip-bombs** | Low | High | Magic-byte validation, sandboxed network-isolated extraction, decompression/page/size limits, AV scan |
| **Long-task reliability** (bulk question creation) | Med | Med | ARQ workers with persistence + idempotency keys + progress events |
| **Vendor-reported metrics** in research (cache %, benchmark scores) | — | Low | Treated as directional; validate against our own workload in P4 evals |
