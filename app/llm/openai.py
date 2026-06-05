import json
from typing import AsyncIterator, List, Dict, Any
from openai import AsyncOpenAI
from ..contracts.llm import LLMProvider, LLMEvent
from pydantic import BaseModel

class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gpt-4o"):
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def respond(self, *, instructions: str, input: List[Dict], tools: List[Dict],
                      tool_choice: str = "auto", parallel_tool_calls: bool = True,
                      previous_response_id: str | None = None,
                      stream: bool = True, prompt_cache_key: str | None = None) -> AsyncIterator[LLMEvent]:
        
        messages = [{"role": "system", "content": instructions}] + input
        
        # In a real impl, we'd handle prompt caching and metadata here
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools if tools else None,
            tool_choice=tool_choice if tools else None,
            stream=stream
        )

        if stream:
            async for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield LLMEvent(event_type="text_delta", data=chunk.choices[0].delta.content)
                if chunk.choices and chunk.choices[0].delta.tool_calls:
                    yield LLMEvent(event_type="tool_call_delta", data=chunk.choices[0].delta.tool_calls)
        else:
            msg = response.choices[0].message
            if msg.content:
                yield LLMEvent(event_type="text", data=msg.content)
            if msg.tool_calls:
                yield LLMEvent(event_type="tool_calls", data=msg.tool_calls)

    async def respond_structured(self, *, instructions: str, input: List[Dict],
                                 schema: type[BaseModel], prompt_cache_key: str | None = None) -> BaseModel:
        messages = [{"role": "system", "content": instructions}] + input
        response = await self.client.beta.chat.completions.parse(
            model=self.model,
            messages=messages,
            response_format=schema
        )
        return response.choices[0].message.parsed
