"""Speaker timeline, batch embeddings and same-model voice similarity.

Set EDGESPEAK_API_KEY to start an owned CLI. For an existing gateway, pass
--base-url and optionally set EDGESPEAK_GATEWAY_KEY to its gateway token.
"""

import argparse
import json
import os
from edgespeak import EdgeSpeak


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", help="Audio/video for the speaker timeline")
    parser.add_argument("reference_a", help="First short voice sample")
    parser.add_argument("reference_b", help="Second short voice sample")
    parser.add_argument("--num-speakers", type=int)
    parser.add_argument("--model", default="EdgeSpeak/Lattice-1")
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
        diarization = sdk.diarize(args.audio, num_speakers=args.num_speakers)
        print(json.dumps(diarization, ensure_ascii=False, indent=2))
        voices = sdk.speaker_embedding(
            [args.reference_a, args.reference_b], model=args.model
        )
        print(json.dumps(voices, ensure_ascii=False, indent=2))
        similarity = sdk.speaker_similarity(
            voices["data"][0]["embedding"],
            voices["data"][1]["embedding"],
            model=args.model,
        )
        print(json.dumps(similarity, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
