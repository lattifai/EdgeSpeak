"""Semantic sentences/paragraphs, or resegment a timed transcript with speakers."""
import argparse
import json
from pathlib import Path
from _common import client, connect, output


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
    connect(parser)
    args = parser.parse_args()
    text = Path(args.text_file).read_text(encoding='utf-8-sig') if args.text_file else args.text
    segments = json.loads(Path(args.segments_file).read_text(encoding='utf-8-sig'))['segments'] if args.segments_file else None
    with client(args) as sdk:
        output(sdk.segment(text, segments=segments, threshold=args.threshold,
            paragraph_threshold=args.paragraph_threshold, min_chars=args.min_chars, max_chars=args.max_chars,
            start_margin=args.start_margin, end_margin=args.end_margin))


if __name__ == '__main__':
    main()
