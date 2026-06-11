"""OpenAI-backed QuestionGenerator — the production generation seam.

Wires PS4 prompting (build_quiz_prompt) to the provider's strict Structured Outputs. The pipeline
overrides the citation with the server-chosen evidence span, so even though the model is asked to cite,
grounding does not depend on trusting the model's locator.

Tests use the deterministic fake generator; this path is exercised by the live eval suite (P4).
"""

from __future__ import annotations

import secrets

from app.contracts import LLMProvider
from app.core.prompts.system import SYSTEM_PROMPT
from app.gen.quiz.gen_schemas import GEN_SCHEMA_BY_TYPE, to_full
from app.gen.quiz.params import QuizParams
from app.gen.quiz.prompting import GenDirectives, build_quiz_prompt
from app.gen.quiz.rag import Evidence
from app.gen.quiz.schemas import QuestionType, _QuestionBase


class OpenAIQuestionGenerator:
    def __init__(self, provider: LLMProvider, *, temperature: float = 0.9) -> None:
        self._provider = provider
        self._temperature = temperature

    async def __call__(
        self,
        *,
        qtype: QuestionType,
        evidence: list[Evidence],
        params: QuizParams,
        directives: GenDirectives | None = None,
    ) -> _QuestionBase:
        # Generate CONTENT only (no citation): grounding is attached server-side by the pipeline.
        gen_schema = GEN_SCHEMA_BY_TYPE[qtype]
        prompt = build_quiz_prompt(
            evidence=evidence,
            bloom_level=params.bloom_level,
            qtype=qtype,
            params=params,
            delimiter=secrets.token_hex(4),  # randomized spotlight delimiter per call
            directives=directives,
        )
        gen = await self._provider.respond_structured(
            instructions=SYSTEM_PROMPT,
            input=[{"role": "user", "content": prompt}],
            schema=gen_schema,
            temperature=self._temperature,
        )
        return to_full(qtype, gen)
