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
| [06-work-division.md](06-work-division.md) | One-page ownership map + handoffs |
| [07-timeline-and-checkpoints.md](07-timeline-and-checkpoints.md) | Parallel phases + integration checkpoints (CP1–CP6) |

**Context & reference:**
| # | File | Contents |
|---|---|---|
| 01 | [01-overview.md](01-overview.md) | Objective, scope, what changed from v1, product principles |
| 02 | [02-architecture-and-stack.md](02-architecture-and-stack.md) | System architecture diagram, project structure, tech stack |
| 03 | [03-subsystems.md](03-subsystems.md) | Deep-dives: orchestrator, memory, quiz pipeline, security, infra |
| 04 | [04-modules-and-ux.md](04-modules-and-ux.md) | The three functional modules + product UX |
| 08 | [08-open-questions-and-risks.md](08-open-questions-and-risks.md) | Blockers needed from mooKIT + top risks |
| 09 | [09-mookit-api-reference.md](09-mookit-api-reference.md) | Extracted mooKIT API contract (from live OpenAPI spec) |
| 10 | [10-research-and-references.md](10-research-and-references.md) | Research synthesis + citations (2025–2026) |

## Source documents (requirements)
- `../Requirements Document - mooKIT AI Assistant for Instructors .md`
- `../mooKIT AI Assistant Service - Technical Specification Document.md`
- `../details.md` (mooKIT API access: `https://test.mookit.in/docs`, static headers for dev)
