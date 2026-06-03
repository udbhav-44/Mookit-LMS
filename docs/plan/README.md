# mooKIT AI Assistant Service — Implementation Plan (v2)

Research-informed, product-grade plan for building a standalone AI Assistant microservice that lets
instructors drive mooKIT through natural language: generate quizzes from documents, draft/send
announcements, and publish lectures — all with human-in-the-loop confirmation.

> **Product north star:** *"We make suggestions. You make decisions."*
> Task-specific tools (not one open chatbot), grounded + cited generation, output that lands directly
> in real mooKIT objects, and provenance tracking ("AI-generated · edited by you").

## Locked decisions
| Decision | Choice |
|---|---|
| Language / framework | Python 3.12 + FastAPI |
| LLM provider | OpenAI (Responses API), behind a swappable `LLMProvider` interface |
| mooKIT auth | Pass-through (frontend forwards `course` / `token` / `uid`; service stays credential-stateless) |
| MVP scope | All three modules (Assessment, Announcement, Lecture) built in parallel |
| Infra | CPU only — **no GPU** (g4dn.xlarge is unnecessary; all inference is via OpenAI's API) |
| Team | 2 developers (Dev A = Platform/Integration/Security infra, Dev B = AI Brain & Domain Logic) |

## Documents

**Core work plan (start here):**
| File | Contents |
|---|---|
| [dev-a-workplan.md](dev-a-workplan.md) | **Comprehensive work plan for Dev A** — Platform, Integration & Security infra (P0–P5, tasks, acceptance criteria) |
| [dev-b-workplan.md](dev-b-workplan.md) | **Comprehensive work plan for Dev B** — AI Brain & Domain Logic (P0–P5, tasks, acceptance criteria) |
| [05-shared-contracts.md](05-shared-contracts.md) | The 7 interfaces both devs build against (frozen at CP1) |
| [07-timeline-and-checkpoints.md](07-timeline-and-checkpoints.md) | Parallel phases + integration checkpoints (CP1–CP6) |

**Context & reference:**
| File | Contents |
|---|---|
| [01-overview.md](01-overview.md) | Objective, scope, what changed from v1, product principles |
| [09-mookit-api-reference.md](09-mookit-api-reference.md) | Extracted mooKIT API contract (from live OpenAPI spec) |

> Companion docs (02 architecture/stack, 03 subsystem deep-dives, 04 module UX, 08 open-questions/risks,
> 10 research & citations) live in the chat plan summary and can be exported on request — the work plans
> above embed the load-bearing detail from each.

## Source documents (requirements)
- `../Requirements Document - mooKIT AI Assistant for Instructors .md`
- `../mooKIT AI Assistant Service - Technical Specification Document.md`
- `../details.md` (mooKIT API access: `https://test.mookit.in/docs`, static headers for dev)
