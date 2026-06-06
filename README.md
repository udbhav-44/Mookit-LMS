# mooKIT AI Assistant — AI Brain & Domain Logic (Dev B)

A standalone AI Assistant microservice that lets instructors drive mooKIT through natural language:
generate grounded quizzes from documents, draft/send announcements, and publish lectures — all with a
deterministic human confirm before anything publishes or sends.

This repo implements **Dev B's track** (the intelligence + product layer) per
[`docs/plan/dev-b-execution-plan.md`](docs/plan/dev-b-execution-plan.md). It runs **fully solo** against
in-process fakes for Dev A's infra (see `tests/fakes/`), and plugs into Dev A's real infra at the 7
shared contracts (`app/contracts/`).

## What's implemented (CP1–CP6)
- **LLM provider** over the OpenAI Responses API with streamed typed events (`app/llm/`).
- **Plan-then-Execute orchestrator** + two-channel memory + reference resolution (`app/core/`).
- **Tool registry** (permission-filtered) + `common` tools + the three domain modules (`app/tools/`).
- **RAG-grounded quiz pipeline**: per-type strict schemas, PS4 prompting, misconception distractors,
  multi-stage verification, descriptive rubrics, conversational knobs (`app/gen/quiz/`).
- **Faithful previews + `ProposedAction`** for all three flows; publish tools only ever *propose*
  (`app/preview/`, `app/tools/`).
- **Safety**: spotlighting, guardrail screening, and an injection red-team proving
  `unconfirmed_actions == 0` (`app/core/`, `app/evals/`).

## Quick start
```bash
# Install uv (https://docs.astral.sh/uv) then:
uv venv --python 3.12
uv pip install -e ".[dev]"

# Offline test suite (no OpenAI key needed — uses deterministic fakes):
uv run pytest -q -m "not live"

# Eval metrics:
uv run python scripts/eval_report.py

# Live streaming check (requires OPENAI_API_KEY in .env):
uv run pytest -q -m live

# Lint + types:
uv run ruff check app tests scripts && uv run mypy app
```

## Layout
```
app/
  contracts/   # the 7 shared interfaces (co-owned with Dev A)
  llm/         # OpenAI Responses provider, strict-schema helper, events
  core/        # orchestrator, memory, reference_resolver, prompts, guardrails, hashing
  tools/       # registry + echo + common + assessment/announcement/lecture
  gen/         # quiz pipeline (rag/prompting/schemas/distractors/verify/rubric/params/pipeline)
               # + announcement.py, lecture_meta.py, provenance.py
  preview/     # faithful PreviewRender builders + markdown sanitizer
  evals/       # quiz_quality, hallucination, injection_redteam
scripts/       # eval_report.py (runs the harness with fakes)
sample-ui/     # editable quiz-preview React component + confirm dialog (B5.3)
tests/         # mirrors app/ ; fakes/ holds the solo-dev unblock kit
docs/          # plan/, ai-architecture.md, demo-script.md, prompt-library.md, eval-report.md
```

## Docs
- [AI architecture](docs/ai-architecture.md) · [Demo script](docs/demo-script.md) ·
  [Prompt library](docs/prompt-library.md) · [Eval report](docs/eval-report.md)
- Plan: [`docs/plan/`](docs/plan/) (overview, contracts, work plans, execution plan).

> Infra (FastAPI app, SSE, tenancy, confirmation gate, file ingestion, deployment) is **Dev A's track**
> and is stubbed here by the fakes in `tests/fakes/`.
