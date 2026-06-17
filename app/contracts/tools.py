from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel, Field

from .context import RequestContext
from .errors import ErrorInfo
from .preview import PreviewRender

RiskTier = Literal["read", "draft", "publish"]

class ToolResult(BaseModel):           # returned by read/draft tools — fed back to the model
    ok: bool
    data: Any = None
    artifact_id: str | None = None     # if the tool created/updated an artifact
    message: str | None = None
    error: ErrorInfo | None = None


class ClarificationOption(BaseModel):
    """One selectable answer for a clarifying question."""

    id: str
    label: str


class ClarificationQuestion(BaseModel):
    """A single question the assistant asks the instructor to resolve ambiguity.

    Mirrors the multiple-choice + free-text UX: the UI renders ``options`` as selectable
    chips (radio when ``allow_multiple`` is false, checkboxes otherwise) plus an "Other"
    free-text field when ``allow_free_text`` is set.
    """

    id: str
    prompt: str
    options: list[ClarificationOption] = Field(default_factory=list)
    allow_multiple: bool = False
    allow_free_text: bool = True


class ClarificationRequest(BaseModel):
    """Returned by the ``ask_user`` tool — pauses the turn to collect a decision.

    Like ProposedAction, this is NEVER fed back to the model as a tool output; the
    orchestrator surfaces it as a ``clarification`` SSE event and ends the turn. The
    instructor's selection arrives as the next user message, which auto-continues the task.
    """

    questions: list[ClarificationQuestion]
    preamble: str | None = None       # optional one-line context shown above the questions

class ProposedAction(BaseModel):       # returned by publish tools — NOT executed inline
    action: str                        # e.g. "publish_assessment", "send_announcement", "publish_lecture"
    target_ref: dict                   # server-resolved target (e.g. {assessment_type, assessment_id})
    payload: dict                      # exact mooKIT request body that WILL be sent
    preview: PreviewRender             # faithful human-readable render of what will happen
    content_hash: str                  # sha256 of canonicalized payload; binds the confirm token

class Tool(ABC):
    name: str                          # snake_case, stable; appears in OpenAI tool schema + audit log
    description: str
    risk_tier: RiskTier
    parameters_schema: dict            # strict JSON Schema (additionalProperties:false, all required)

    @abstractmethod
    async def run(
        self, ctx: RequestContext, args: dict
    ) -> ToolResult | ProposedAction | ClarificationRequest: ...
