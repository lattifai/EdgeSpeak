"""Run with an activated device and a CLI build supporting --sdk."""
import argparse
import json
from edgespeak import EdgeSpeak

parser = argparse.ArgumentParser()
parser.add_argument("audio")
args = parser.parse_args()
with EdgeSpeak() as client:
    print(json.dumps(client.transcribe(args.audio, diarize=True), ensure_ascii=False, indent=2))
