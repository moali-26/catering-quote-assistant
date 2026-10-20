"""OpenAI Chat Completions adapter.  pip install openai ; set OPENAI_API_KEY and OPENAI_MODEL."""
import json
import os

from ..llm import LLMResponse, ToolCall


def to_openai_messages(system, messages):
    out = [{'role': 'system', 'content': system}]
    for m in messages:
        if m['role'] == 'user':
            out.append({'role': 'user', 'content': m['content']})
        elif m['role'] == 'assistant':
            entry = {'role': 'assistant', 'content': m.get('content') or None}
            calls = m.get('tool_calls') or []
            if calls:
                entry['tool_calls'] = [{
                    'id': c['id'], 'type': 'function',
                    'function': {'name': c['name'], 'arguments': json.dumps(c['arguments'])},
                } for c in calls]
            out.append(entry)
        elif m['role'] == 'tool':
            out.append({'role': 'tool', 'tool_call_id': m['tool_call_id'], 'content': m['content']})
    return out


def to_openai_tools(tools):
    return [{'type': 'function', 'function': {
        'name': t['name'], 'description': t['description'], 'parameters': t['input_schema']}}
        for t in tools]


def from_openai_response(response):
    message = response.choices[0].message
    calls = []
    for c in message.tool_calls or []:
        try:
            args = json.loads(c.function.arguments or '{}')
        except ValueError:
            args = None  # malformed JSON from the model -> tools return invalid_input
        calls.append(ToolCall(id=c.id, name=c.function.name, arguments=args))
    return LLMResponse(content=message.content or '', tool_calls=calls)


class OpenAILLM:
    def __init__(self, model=None, client=None):
        if client is None:
            import openai  # lazy: only needed if the team picks OpenAI
            client = openai.OpenAI(api_key=os.environ.get('OPENAI_API_KEY'), timeout=60.0, max_retries=1)
        self.client = client
        self.model = model or os.environ.get('OPENAI_MODEL')
        if not self.model:
            raise ValueError('Set OPENAI_MODEL (or pass model=...) to the model name you chose.')

    def generate(self, system, messages, tools):
        response = self.client.chat.completions.create(
            model=self.model, messages=to_openai_messages(system, messages),
            tools=to_openai_tools(tools))
        return from_openai_response(response)
