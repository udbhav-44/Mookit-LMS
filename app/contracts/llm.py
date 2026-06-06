from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel


class LLMEvent(BaseModel):
    event_type: str
    data: Any

class LLMProvider(ABC):
    @abstractmethod
    def respond(self, *, instructions: str, input: list[dict], tools: list[dict],
                tool_choice: str = "auto", parallel_tool_calls: bool = True,
                previous_response_id: str | None = None,
                stream: bool = True, prompt_cache_key: str | None = None,
                temperature: float | None = None) -> AsyncIterator[LLMEvent]: ...

    @abstractmethod
    async def respond_structured(self, *, instructions: str, input: list[dict],
                                 schema: type[BaseModel], prompt_cache_key: str | None = None,
                                 temperature: float | None = None) -> BaseModel: ...
