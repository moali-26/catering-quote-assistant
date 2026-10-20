"""Provider-neutral model interface.

Conversation history uses one internal message format. Each provider adapter
(see ai_service/providers/) translates it to and from its own API:

    {'role': 'user', 'content': str}
    {'role': 'assistant', 'content': str, 'tool_calls': [ToolCall, ...]}
    {'role': 'tool', 'tool_call_id': str, 'name': str, 'content': str (JSON)}

Tools are passed as {'name', 'description', 'input_schema'} dicts, the same
shape as quote_engine.ai_tool.TOOL_DEFINITION.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Any  # parsed JSON object; may be malformed if the model misbehaves


@dataclass
class LLMResponse:
    content: str = ''
    tool_calls: List[ToolCall] = field(default_factory=list)


class LLMClient(Protocol):
    def generate(self, system: str, messages: List[Dict[str, Any]],
                 tools: List[Dict[str, Any]]) -> LLMResponse:
        """Return the model's next turn: text, tool calls, or both."""
        ...


class ScriptedLLM:
    """Fake model for tests and offline demos. Returns pre-written turns in order.

    Each script entry is an LLMResponse, or a callable(system, messages, tools)
    returning one, so tests can inspect what the model would have seen.
    """

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def generate(self, system, messages, tools):
        self.calls.append({'system': system, 'messages': [dict(m) for m in messages],
                           'tools': tools})
        if not self.script:
            raise RuntimeError('ScriptedLLM ran out of scripted responses')
        step = self.script.pop(0)
        return step(system, messages, tools) if callable(step) else step
