"""Capability views of the live gateway catalog; never maintain a model registry here."""
from copy import deepcopy
from typing import Any, Mapping
from ._responses import ModelGroup

# Group endpoint capabilities, not model names: the gateway owns model identity,
# availability and installation state. Unknown endpoints remain visible in other.
_GROUPS = (
    ("transcription", "Transcription", "Convert audio to text. Pass the model ID to transcribe(model=...). Speaker selection is separate: transcribe(diarization_model=...).", {
        "/v1/audio/transcriptions": "transcribe"}),
    ("alignment", "Forced alignment", "Align supplied text with audio. Pass the model ID to align(model=...) or diff_align(model=...) where advertised.", {
        "/v1/audio/alignments": "align", "/v1/audio/diff-alignments": "diff_align"}),
    ("diarization", "Speaker diarization", "Find who spoke when. Use diarize(model=...) or transcribe(diarization_model=...) with a gateway supporting explicit speaker selection.", {
        "/v1/speaker/diarizations": "diarize"}),
    ("speaker_embeddings", "Speaker embeddings", "Extract voice embeddings with speaker_embedding(model=...). Compare only embeddings from the same model.", {
        "/v1/speaker/embeddings": "speaker_embedding"}),
    ("speaker_similarity", "Speaker similarity", "Compare same-model voice embeddings with speaker_similarity(model=...). Scores are not calibrated probabilities.", {
        "/v1/speaker/similarity": "speaker_similarity"}),
    ("speech", "Speech synthesis", "Generate speech through POST /v1/audio/speech; this SDK has no speech-synthesis convenience method yet. Check voice, language and instruction metadata.", {
        "/v1/audio/speech": None}),
    ("text_generation", "Text generation", "Generate text using the endpoint advertised by each model; endpoint support can differ between models in this group.", {
        "/v1/chat/completions": "chat_completions", "/v1/responses": "responses", "/v1/messages": "messages"}),
    ("tokenization", "Tokenization", "Inspect a text model's tokens with tokenize(model=...).", {
        "/v1/tokenize": "tokenize"}),
    ("segmentation", "Text segmentation", "Split text into semantic sentences or paragraphs with segment(); the runtime selects the segmentation model.", {
        "/v1/text/segmentations": "segment"}),
    ("normalization", "Text normalization", "Convert written/spoken text forms with text_normalizations(); inspect supported languages and classes in the model metadata.", {
        "/v1/text/normalizations": "text_normalizations"}),
    ("upsampling", "Audio upsampling", "Increase audio sample rate with upsample(); the runtime selects the audio model.", {
        "/v1/audio/upsamplings": "upsample"}),
)


def group_models(catalog: Mapping[str, Any]) -> dict[str, ModelGroup]:
    """Build an annotated view without changing IDs or guessing missing state."""
    groups: dict[str, ModelGroup] = {}
    known_endpoints = {endpoint for _, _, _, routes in _GROUPS for endpoint in routes}
    for key, title, description, routes in _GROUPS:
        selected = [model for model in catalog["data"]
                    if set(model.get("supported_endpoints", ())).intersection(routes)]
        if not selected:
            continue
        endpoints = sorted({endpoint for model in selected
                            for endpoint in model.get("supported_endpoints", ()) if endpoint in routes})
        groups[key] = {"title": title, "description": description,
                       "supported_endpoints": endpoints,
                       "sdk_methods": sorted({method for endpoint in endpoints if (method := routes[endpoint]) is not None}),
                       "models": deepcopy(sorted(selected, key=lambda model: model.get("id", "")))}
    other = [model for model in catalog["data"]
             if not model.get("supported_endpoints")
             or set(model["supported_endpoints"]) - known_endpoints]
    if other:
        groups["other"] = {
            "title": "Other or unspecified capabilities",
            "description": "The gateway omitted endpoint capabilities or advertises endpoints this SDK does not group yet. Inspect supported_endpoints; do not infer support from the model name.",
            "supported_endpoints": sorted({endpoint for model in other
                                           for endpoint in model.get("supported_endpoints", ())
                                           if endpoint not in known_endpoints}),
            "sdk_methods": [], "models": deepcopy(other),
        }
    return groups
