"""Try the owner checkout from the terminal before the app exists.

    python -m billing checkout --owner demo-owner-1
    python -m billing check cs_test_... --owner demo-owner-1

Needs STRIPE_SECRET_KEY (sk_test_...) and STRIPE_PRICE_ID (price_...) in the environment.
"""
import argparse
import json
import sys

from .stripe_billing import BillingConfig, BillingError, create_checkout, verify_checkout

DEMO_SUCCESS_URL = 'https://example.com/billing/success'
DEMO_CANCEL_URL = 'https://example.com/billing/cancel'


def main():
    parser = argparse.ArgumentParser(prog='python -m billing')
    commands = parser.add_subparsers(dest='command', required=True)
    start = commands.add_parser('checkout', help='create a test checkout link')
    start.add_argument('--owner', default='demo-owner-1')
    check = commands.add_parser('check', help='ask Stripe whether a checkout was paid')
    check.add_argument('session_id')
    check.add_argument('--owner', default=None)
    args = parser.parse_args()

    try:
        config = BillingConfig.from_env()
        if args.command == 'checkout':
            result = create_checkout(config, args.owner, success_url=DEMO_SUCCESS_URL,
                                     cancel_url=DEMO_CANCEL_URL)
            print('Open this link and pay with test card 4242 4242 4242 4242:')
            print(result['url'])
            print(f"\nThen run: python -m billing check {result['session_id']} --owner {args.owner}")
        else:
            print(json.dumps(verify_checkout(config, args.session_id, owner_id=args.owner),
                             indent=2))
    except BillingError as exc:
        sys.exit(f'Error: {exc}')


if __name__ == '__main__':
    main()
