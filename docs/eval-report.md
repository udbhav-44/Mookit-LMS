# Eval Report (Dev B)

Reproducible offline metrics from `python scripts/eval_report.py` (deterministic fakes — no OpenAI key
required). The live LLM-scored variants run via the `@pytest.mark.live` suite when a key is present.

> **Caveat (per the plan):** LLM evaluators are treated as *flaggers*, not judges — they misalign with
> human experts. The offline scorer is a deterministic structural proxy; treat absolute numbers as
> directional and watch *regressions*, not the absolute value.

## Quiz quality (structural proxy scorer)
Fixed doc: the seeded photosynthesis corpus; 5-question draft (one of each type).

| Dimension | Score |
|---|---|
| understandability | 1.00 |
| relevance | 1.00 |
| grammar | 1.00 |
| clarity | 1.00 |
| answerability | 1.00 |
| bloom_alignment | 0.90 |
| **overall** | **0.983** |

Flagged questions: 0. (`bloom_alignment` is intentionally capped at 0.65 for higher-order items to
reflect the known weakness; this draft is lower-order, so it scores 0.90.)

## Grounding / hallucination
| Metric | Value |
|---|---|
| questions | 5 |
| ungrounded | 0 |
| unfaithful citations | 0 |
| ungrounded rate | 0.0 |
| faithful | ✅ true |

Every question carries a source-span citation whose quote is supported by the retrieved evidence
(grounding is enforced server-side — the citation is the span the pipeline chose, not a model-supplied
locator).

## Injection red-team (the security gate)
Adversarial setup: a **fully compromised** model that obeys the injection and tries to publish/send on
every case.

| Metric | Value |
|---|---|
| cases | 3 |
| **unconfirmed_actions** | **0** ✅ |
| pending_confirmations | 3 |
| passed | ✅ true |

**Result:** zero unconfirmed publish/send actions are reachable. Even with the model compromised, every
attempt produced a `pending_confirmation` (human gate) and **no** mooKIT write occurred. This is the
load-bearing guarantee — it holds architecturally (publish tools only ever return a `ProposedAction`),
not probabilistically. Covered by `tests/evals/test_injection_redteam.py` and `tests/test_cp4_flows.py`.

## How to reproduce
```bash
uv run python scripts/eval_report.py            # JSON metrics
uv run pytest -q -m "not live"                  # full offline suite (incl. evals + red-team)
```
