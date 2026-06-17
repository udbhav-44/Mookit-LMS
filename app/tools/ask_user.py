"""ask_user — general-purpose clarifying-question tool.

A read-tier tool the model calls whenever a decision is genuinely the instructor's to make:
an ambiguous reference, a consequential value it would otherwise assume (question count,
audience, what gets published), or a fork it cannot resolve from context. It NEVER mutates
anything; it pauses the turn so the UI can present selectable options (plus a free-text
"Other") and the instructor's answer flows back as the next message, auto-continuing the task.

Guidance for *when* to call this lives in the system prompt. Keep questions to the genuinely
consequential / ambiguous; use sensible defaults for trivial cosmetic choices.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.contracts import (
    ClarificationOption,
    ClarificationQuestion,
    ClarificationRequest,
    RequestContext,
    Tool,
)
from app.llm.schema import strict_schema


class _Option(BaseModel):
    id: str = Field(description="Stable machine id for this choice, e.g. 'ten' or 'replicate'.")
    label: str = Field(description="Human-readable choice shown to the instructor.")


class _Question(BaseModel):
    id: str = Field(description="Stable machine id for this question, e.g. 'question_count'.")
    prompt: str = Field(description="The question text, without listing the options inline.")
    options: list[_Option] = Field(
        default_factory=list,
        description="2+ selectable choices. The UI also always offers a free-text 'Other'.",
    )
    allow_multiple: bool = Field(
        default=False, description="True if more than one option may be selected."
    )
    allow_free_text: bool = Field(
        default=True, description="True if the instructor may type a custom answer."
    )


class AskUserArgs(BaseModel):
    questions: list[_Question] = Field(
        description="One or more related questions to ask at once (a small form)."
    )
    preamble: str | None = Field(
        default=None,
        description="Optional one-line context shown above the questions.",
    )


class AskUserTool(Tool):
    name = "ask_user"
    description = (
        "Ask the instructor a clarifying question (selectable options + free-text) when a "
        "consequential or ambiguous decision is theirs to make and you cannot resolve it from "
        "context — e.g. how many quiz questions, which document, what audience. Do NOT use it "
        "for trivial cosmetic defaults. The turn pauses; the instructor's selection arrives as "
        "the next message and continues the task. Reuse answers already given in this "
        "conversation instead of re-asking."
    )
    risk_tier = "read"
    parameters_schema = strict_schema(AskUserArgs)

    async def run(self, ctx: RequestContext, args: dict[str, Any]) -> ClarificationRequest:
        parsed = AskUserArgs.model_validate(args)
        return ClarificationRequest(
            preamble=parsed.preamble,
            questions=[
                ClarificationQuestion(
                    id=q.id,
                    prompt=q.prompt,
                    allow_multiple=q.allow_multiple,
                    allow_free_text=q.allow_free_text,
                    options=[ClarificationOption(id=o.id, label=o.label) for o in q.options],
                )
                for q in parsed.questions
            ],
        )
