"""Speaker timeline, batch embeddings and same-model voice similarity."""
import argparse
from _common import client, connect, output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('audio', help='Audio/video for the speaker timeline')
    parser.add_argument('reference_a', help='First short voice sample')
    parser.add_argument('reference_b', help='Second short voice sample')
    parser.add_argument('--num-speakers', type=int)
    parser.add_argument('--model', default='EdgeSpeak/Lattice-1')
    connect(parser)
    args = parser.parse_args()
    with client(args) as sdk:
        output(sdk.diarize(args.audio, num_speakers=args.num_speakers))
        voices = sdk.speaker_embedding([args.reference_a, args.reference_b], model=args.model)
        output(voices)
        output(sdk.speaker_similarity(voices['data'][0]['embedding'], voices['data'][1]['embedding'], model=args.model))


if __name__ == '__main__':
    main()
