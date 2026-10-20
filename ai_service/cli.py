"""Chat with the assistant in the terminal.

    python3 -m ai_service.cli --provider anthropic
    python3 -m ai_service.cli --provider openai --now 2026-10-18T12:00:00-07:00

--now freezes the clock (the sample inquiries assume October 18, 2026).
Type 'quit' to exit, 'debug' to toggle tool-call output.
"""
import argparse
import json

from .conversation import Conversation
from .data_loader import load_context
from .providers import make_llm


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--provider', required=True, help='anthropic or openai')
    parser.add_argument('--model', default=None)
    parser.add_argument('--dataset', default='demo', choices=['demo', 'sample', 'full'])
    parser.add_argument('--now', default=None, help='ISO datetime with offset to freeze the clock')
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()

    convo = Conversation(llm=make_llm(args.provider, model=args.model),
                         context=load_context(args.dataset, args.now))
    debug = args.debug
    print(f"Chatting with {convo.context.business_name}. Type 'quit' to exit.\n")
    while True:
        try:
            text = input('You: ').strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text.lower() in ('quit', 'exit'):
            break
        if text.lower() == 'debug':
            debug = not debug
            print(f'(debug {"on" if debug else "off"})')
            continue
        if not text:
            continue
        turn = convo.send(text)
        if debug:
            for call in turn.tool_calls:
                print(f"  [tool] {call['name']} {json.dumps(call['arguments'])}")
                print(f"         -> {json.dumps(call['result'])[:300]}")
            if turn.warnings:
                print(f'  [warnings] {turn.warnings}')
        print(f'\nAssistant: {turn.reply}\n')
        if turn.ready_to_submit:
            print('  (ready to submit for owner review)\n')


if __name__ == '__main__':
    main()
