from abc import ABC, abstractmethod
from typing import Literal, Any
from pydantic import BaseModel
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
    async def run(self, ctx: RequestContext, args: dict) -> ToolResult | ProposedAction: ...
