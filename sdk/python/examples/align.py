"""Align text or TXT/JSON/SRT/ASS/SSA references; original cue timing is ignored.

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
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--text")
    source.add_argument("--text-file")
    parser.add_argument("--text-format", choices=["txt", "json", "srt", "ass", "ssa"])
    parser.add_argument("--language")
    parser.add_argument("--model")
    parser.add_argument("--start", type=float)
    parser.add_argument("--end", type=float)
    parser.add_argument(
        "--search-effort", choices=["standard", "extended", "auto"], default="standard"
    )
    parser.add_argument("--protected-term", action="append")
    parser.add_argument(
        "--text-normalization", type=json.loads, help="API normalization JSON object"
    )
    parser.add_argument("--audio-track", type=int)
    parser.add_argument("--audio-channel")
    parser.add_argument(
        "--semantic", action=argparse.BooleanOptionalAction, default=None
    )
    parser.add_argument("--threshold", type=float)
    parser.add_argument("--min-chars", type=int)
    parser.add_argument("--max-chars", type=int)
    parser.add_argument("--start-margin", type=float)
    parser.add_argument("--end-margin", type=float)
    parser.add_argument("--progress", action="store_true")
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
        result = sdk.align(
            args.audio,
            text=args.text,
            text_file=args.text_file,
            text_format=args.text_format,
            language=args.language,
            model=args.model,
            start=args.start,
            end=args.end,
            search_effort=args.search_effort,
            protected_terms=args.protected_term,
            text_normalization=args.text_normalization,
            audio_track=args.audio_track,
            audio_channel=args.audio_channel,
            semantic_sentence_enabled=args.semantic,
            threshold=args.threshold,
            min_chars=args.min_chars,
            max_chars=args.max_chars,
            start_margin=args.start_margin,
            end_margin=args.end_margin,
            progress=args.progress,
        )
        if args.progress:
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
