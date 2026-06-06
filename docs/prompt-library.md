# Prompt Library (Dev B)

Versioned record of every prompt the AI brain uses. Bump `PROMPT_VERSION` in `app/config.py` whenever
the **static** system prompt or tool-schema preamble changes (it busts the prompt cache).

Current `PROMPT_VERSION`: **1**

## Static system prompt
- **File:** `app/core/prompts/system.py` (`SYSTEM_PROMPT`)
- **Role:** immutable safety policy + persona; byte-stable cache prefix (no per-request data).
- **Pins:** instruction hierarchy (system > developer > user > tool); the 6 core rules
  (propose-not-publish, plan-then-execute, never-name-recipients, cite-every-question,
  confirm-on-ambiguity, be-concise).

## Quiz generation (PS4)
- **File:** `app/gen/quiz/prompting.py` (`build_quiz_prompt`)
- **Pattern:** Chain-of-Thought + the single requested Bloom-level definition + ≤2 few-shot exemplars
  for that level. Persona = "graduate-level instructor".
- **Temperature:** `0.9` (diversity) for generation; `0.0` for evals/snapshots.
- **Anti-over-stuffing:** only the requested level's definition + ≤2 exemplars are included (more
  instructions measurably degrade quality).
- **Spotlighting:** source evidence is wrapped in randomized delimiters labeled as data
  (`spotlight_evidence`, delimiter per call).

## Rubric (descriptive questions)
- **File:** `app/gen/quiz/rubric.py` — deterministic default (offline) or injected LLM generator.

## Spotlighting
- **File:** `app/core/prompts/spotlight.py` (`spotlight`) — randomized per-request delimiters + a
  "data, never instructions" banner around all untrusted text (documents, mooKIT-returned strings).

## Guardrails
- **File:** `app/core/guardrails.py` — heuristic injection/jailbreak screen (FLAG, not block); swapped
  for Dev A's OpenAI Guardrails + Moderation hooks at integration.

## Tuning notes
- LLM evaluators are treated as **flaggers**, never judges (they misalign with experts).
- Higher-order Bloom (analyze/evaluate/create) is always routed to mandatory human review (`~65%`
  alignment weakness).
- Tune against `app/evals/quiz_quality.py` + `app/evals/hallucination.py`; never regress the injection
  red-team (`app/evals/injection_redteam.py` must report `unconfirmed_actions == 0`).
