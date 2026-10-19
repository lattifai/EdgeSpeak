"""Transcribe media with optional speaker labels, word timestamps and sentences.

Set EDGESPEAK_API_KEY to start an owned CLI. For an existing gateway, pass
--base-url and optionally set EDGESPEAK_GATEWAY_KEY to its gateway token.
"""

import argparse
import json
import os
from edgespeak import EdgeSpeak


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio")
    parser.add_argument("--model")
    parser.add_argument("--language")
    parser.add_argument("--prompt")
    parser.add_argument(
        "--timestamp-granularity", action="append", choices=["word", "segment"]
    )
    parser.add_argument("--diarize", action="store_true")
    parser.add_argument(
        "--response-format", choices=["json", "verbose_json", "diarized_json", "text"]
    )
    parser.add_argument(
        "--word-timestamps", action=argparse.BooleanOptionalAction, default=None
    )
    parser.add_argument(
        "--semantic", action=argparse.BooleanOptionalAction, default=None
    )
    parser.add_argument("--min-chars", type=int)
    parser.add_argument("--max-chars", type=int)
    parser.add_argument("--start-margin", type=float)
    parser.add_argument("--end-margin", type=float)
    parser.add_argument("--candidates", type=int)
    parser.add_argument(
        "--stream", action="store_true", help="SSE; desktop gateway only"
    )
    parser.add_argument(
        "--base-url", help="Attach to an existing gateway; never stop it"
    )
    args = parser.parse_args()
    # With no base_url, the SDK starts its own CLI and reads EDGESPEAK_API_KEY.
    # Existing gateways use their own gateway token, not an account API KEY.
    with EdgeSpeak(
        base_url=args.base_url,
        gateway_key=os.environ.get("EDGESPEAK_GATEWAY_KEY") if args.base_url else None,
    ) as sdk:
        result = sdk.transcribe(
            args.audio,
            model=args.model,
            language=args.language,
            diarize=args.diarize,
            response_format=args.response_format,
            stream=args.stream,
            prompt=args.prompt,
            timestamp_granularities=args.timestamp_granularity,
            word_timestamp_enabled=args.word_timestamps,
            candidates=args.candidates,
            semantic_sentence_enabled=args.semantic,
            min_chars=args.min_chars,
            max_chars=args.max_chars,
            start_margin=args.start_margin,
            end_margin=args.end_margin,
        )
        if args.stream:
            with result as events:
                for event in events:
                    print(json.dumps(event, ensure_ascii=False, indent=2))
        else:
            print(
                result
                if isinstance(result, str)
                else json.dumps(result, ensure_ascii=False, indent=2)
            )


if __name__ == "__main__":
    main()
