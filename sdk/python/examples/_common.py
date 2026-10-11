"""Shared connection options; credentials stay in environment variables."""
import json
import os
from edgespeak import EdgeSpeak


def connect(parser):
    parser.add_argument('--base-url', help='Attach to an existing gateway; never stop it')


def client(args):
    if args.base_url:
        return EdgeSpeak(base_url=args.base_url, gateway_key=os.environ.get('EDGESPEAK_GATEWAY_KEY'))
    return EdgeSpeak()


def output(result):
    print(result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=2))
