"""B — AI conversation service (provider-neutral).

The model handles language: understanding the customer, asking questions,
choosing menu items. Python code handles everything that must be correct:
menu lookup, prices, rules, and the dollar amounts the reply may mention.

Main entry point::

    from ai_service import Conversation, ServerContext
    convo = Conversation(llm=some_llm_client, context=server_context)
    reply = convo.send("Lunch for 40 next Friday in Culver City")

See docs/ai-conversation.md.
"""
from .context import ServerContext, demo_location_resolver
from .conversation import Conversation, TurnResult
from .llm import LLMClient, LLMResponse, ScriptedLLM, ToolCall

__all__ = [
    'Conversation', 'TurnResult', 'ServerContext', 'demo_location_resolver',
    'LLMClient', 'LLMResponse', 'ScriptedLLM', 'ToolCall',
]
