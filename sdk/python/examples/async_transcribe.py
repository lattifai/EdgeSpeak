"""Transcribe files concurrently; optionally stream alignment progress.

Set EDGESPEAK_API_KEY for an owned service:
    python async_transcribe.py first.wav second.wav --align

For an existing gateway, use --base-url and EDGESPEAK_GATEWAY_KEY instead.
"""
import argparse
import asyncio
import json
import os

from edgespeak import AsyncEdgeSpeak


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('audio', nargs='+')
    parser.add_argument('--language')
    parser.add_argument('--max-concurrency', type=int, default=2)
    parser.add_argument('--align', action='store_true', help='Stream alignment using the recognized text')
    parser.add_argument('--base-url', help='Attach to an existing gateway; never stop it')
    args = parser.parse_args()

    # Without base_url, start an owned CLI using EDGESPEAK_API_KEY.
    # Attached mode uses a gateway token; it does not change server concurrency.
    async with AsyncEdgeSpeak(
        base_url=args.base_url,
        gateway_key=os.environ.get('EDGESPEAK_GATEWAY_KEY') if args.base_url else None,
        max_concurrency=args.max_concurrency,
    ) as sdk:
        # gather preserves input order; max_concurrency limits requests in flight.
        results = await asyncio.gather(
            *(sdk.transcribe(audio, language=args.language) for audio in args.audio)
        )
        for audio, result in zip(args.audio, results):
            print(json.dumps({'audio': audio, 'transcription': result}, ensure_ascii=False, indent=2))
            if args.align:
                async with sdk.align(audio, text=result['text'], progress=True) as events:
                    async for event in events:
                        print(json.dumps(event, ensure_ascii=False, indent=2))
    # async with closes streams and stops only the CLI owned by this client.


if __name__ == '__main__':
    asyncio.run(main())
