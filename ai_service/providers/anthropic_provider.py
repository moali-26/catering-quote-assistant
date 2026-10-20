"""Anthropic (Claude) Messages API adapter.  pip install anthropic ; set ANTHROPIC_API_KEY."""
import os

from ..llm import LLMResponse, ToolCall

DEFAULT_MODEL = 'claude-sonnet-5-5'


def to_anthropic_messages(messages):
    """Translate internal history. Consecutive same-role messages are merged (API requirement)."""
    out = []

    def add(role, blocks):
        if not blocks:
            return
        if out and out[-1]['role'] == role:
            out[-1]['content'].extend(blocks)
        else:
            out.append({'role': role, 'content': list(blocks)})

    for m in messages:
        if m['role'] == 'user':
            add('user', [{'type': 'text', 'text': m['content']}] if m.get('content') else [])
        elif m['role'] == 'assistant':
            blocks = [{'type': 'text', 'text': m['content']}] if m.get('content') else []
            for call in m.get('tool_calls') or []:
                args = call['arguments'] if isinstance(call['arguments'], dict) else {}
                blocks.append({'type': 'tool_use', 'id': call['id'], 'name': call['name'],
                               'input': args})
            add('assistant', blocks)
        elif m['role'] == 'tool':
            add('user', [{'type': 'tool_result', 'tool_use_id': m['tool_call_id'],
                          'content': m['content']}])
    return out


def to_anthropic_tools(tools):
    return [{'name': t['name'], 'description': t['description'],
             'input_schema': t['input_schema']} for t in tools]


def from_anthropic_response(response):
    text, calls = [], []
    for block in response.content:
        if block.type == 'text':
            text.append(block.text)
        elif block.type == 'tool_use':
            calls.append(ToolCall(id=block.id, name=block.name, arguments=block.input))
    return LLMResponse(content='\n'.join(text), tool_calls=calls)


class AnthropicLLM:
    def __init__(self, model=None, max_tokens=1500, client=None):
        if client is None:
            import anthropic  # lazy: only needed if the team picks Claude
            # 60 s per request, 1 retry: a stuck network call fails visibly instead of hanging.
            client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'),
                                         timeout=60.0, max_retries=1)
        self.client = client
        self.model = model or (os.environ.get('ANTHROPIC_MODEL') or '').strip() or DEFAULT_MODEL  # empty var = default
        self.max_tokens = max_tokens

    def generate(self, system, messages, tools):
        response = self.client.messages.create(
            model=self.model, max_tokens=self.max_tokens, system=system,
            messages=to_anthropic_messages(messages), tools=to_anthropic_tools(tools))
        return from_anthropic_response(response)
