"""Semantic sentences/paragraphs, or resegment a timed transcript with speakers."""
import argparse
import json
import os
from pathlib import Path
from edgespeak import EdgeSpeak


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--text')
    source.add_argument('--text-file', help='UTF-8 plain text')
    source.add_argument('--segments-file', help='Exported transcript JSON with segments')
    parser.add_argument('--threshold', type=float)
    parser.add_argument('--paragraph-threshold', type=float)
    parser.add_argument('--min-chars', type=int)
    parser.add_argument('--max-chars', type=int)
    parser.add_argument('--start-margin', type=float)
    parser.add_argument('--end-margin', type=float)
    parser.add_argument('--base-url', help='Attach to an existing gateway; never stop it')
    args = parser.parse_args()
    text = Path(args.text_file).read_text(encoding='utf-8-sig') if args.text_file else args.text
    segments = json.loads(Path(args.segments_file).read_text(encoding='utf-8-sig'))['segments'] if args.segments_file else None
    # With no base_url, the SDK starts its own CLI and reads EDGESPEAK_API_KEY.
    # Existing gateways use their own gateway token, not an account API KEY.
    with EdgeSpeak(
        base_url=args.base_url,
        gateway_key=os.environ.get('EDGESPEAK_GATEWAY_KEY') if args.base_url else None,
    ) as sdk:
        result = sdk.segment(text, segments=segments, threshold=args.threshold,
            paragraph_threshold=args.paragraph_threshold, min_chars=args.min_chars, max_chars=args.max_chars,
            start_margin=args.start_margin, end_margin=args.end_margin)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
