"""Transcribe media with optional speaker labels, word timestamps and sentences."""
import argparse
from _common import client, connect, output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('audio')
    parser.add_argument('--model')
    parser.add_argument('--language')
    parser.add_argument('--prompt')
    parser.add_argument('--timestamp-granularity', action='append', choices=['word', 'segment'])
    parser.add_argument('--diarize', action='store_true')
    parser.add_argument('--response-format', choices=['json', 'verbose_json', 'diarized_json', 'text'])
    parser.add_argument('--word-timestamps', action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument('--semantic', action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument('--min-chars', type=int)
    parser.add_argument('--max-chars', type=int)
    parser.add_argument('--start-margin', type=float)
    parser.add_argument('--end-margin', type=float)
    parser.add_argument('--candidates', type=int)
    parser.add_argument('--stream', action='store_true', help='SSE; desktop gateway only')
    connect(parser)
    args = parser.parse_args()
    with client(args) as sdk:
        result = sdk.transcribe(args.audio, model=args.model, language=args.language,
            diarize=args.diarize, response_format=args.response_format, stream=args.stream, prompt=args.prompt,
            timestamp_granularities=args.timestamp_granularity,
            word_timestamp_enabled=args.word_timestamps, candidates=args.candidates,
            semantic_sentence_enabled=args.semantic, min_chars=args.min_chars, max_chars=args.max_chars,
            start_margin=args.start_margin, end_margin=args.end_margin)
        if args.stream:
            with result as events:
                for event in events:
                    output(event)
        else:
            output(result)


if __name__ == '__main__':
    main()
