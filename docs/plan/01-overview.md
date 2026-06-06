# 01 — Overview

## Objective
Build a **standalone AI Assistant microservice** that sits between mooKIT instances and an LLM provider.
mooKIT's frontend team builds the production chat UI; **we build the brain + a sample test UI**. The
service is reusable across multiple mooKIT deployments (e.g. `hello.iitk.ac.in`, `learn.online.iitk.ac.in`).

Phase-1 capabilities, all via natural-language chat with confirmation-before-publish:
1. **Assessment generation** from uploaded documents (PDF/DOCX/PPT/TXT/XLSX/CSV).
2. **Announcements** — draft and publish/email.
3. **Lecture publishing** — upload, schedule, publish under a week/module.



## Design principles (from the spec + comparable products)
- **Assist, don't replace** — the instructor is always the final decision-maker.
- **Never publish/send without explicit confirmation.** The confirmation gate is a hard, deterministic boundary.
- **Always preview before publishing**, showing the *actual* payload (rendered final artifact, resolved recipients).
- **Transparency / provenance** — log every action; mark generated content "AI-generated · edited by instructor".
- **Grounded + cited** — every quiz question carries a source-span citation ("view source").
- **Task-specific tools, not one open chatbot** — strongest products (Khanmigo, Copilot Teach) decompose into structured tools.
- **Output lands in the real workflow** — generation writes into actual mooKIT quiz/announcement/lecture objects.
- **Extensible** for future instructor workflows.

