"""Stable, content-free errors shared by ordinary and streaming responses."""
from typing import Any
from datetime import datetime
import json
import logging
import os
import re


API_KEYS_URL = "https://edgespeak.com/account/api-keys"
_LOG = logging.getLogger("edgespeak")


def valid_account_key(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"esak_[A-Za-z0-9_-]{43}", value) is not None


def resolve_account_key(api_key: str | None, base_url: str | None) -> str | None:
    """Return the owned-mode account API KEY from the parameter or environment.

    EDGESPEAK_API_KEY also names the gateway token read by ``edgespeak-cli serve``.
    An environment value that is not an esak_ account key is therefore ignored
    with a warning instead of failing client construction. Values are never logged.
    """
    if api_key is not None:
        if not valid_account_key(api_key):
            raise ValueError(f"The api_key parameter must be an account API KEY (esak_ followed by 43 characters). Create one at {API_KEYS_URL}.")
        if base_url is not None:
            raise ValueError("api_key is only used when the SDK starts its own CLI service.")
        return api_key
    if base_url is not None:
        return None
    value = os.environ.get("EDGESPEAK_API_KEY")
    if valid_account_key(value):
        return value
    if isinstance(value, str) and value.startswith("esak_"):
        raise ValueError(f"The EDGESPEAK_API_KEY environment variable looks like an account API KEY but is malformed (expected esak_ followed by 43 characters). Fix or unset it, or pass api_key. Create one at {API_KEYS_URL}.")
    if value:
        _LOG.warning("Ignoring EDGESPEAK_API_KEY: it is not an account API KEY (esak_...); it may be a gateway token for edgespeak-cli serve. "
                     "Pass api_key to use an account key; otherwise the CLI uses its existing local activation.")
    return None


class EdgeSpeakError(RuntimeError):
    """A gateway failure, with a stable code and optional HTTP status.

    alignment: validated ``error.alignment`` details for alignment failures, for
    example ``{"reason": "search_incomplete", "retry_recommended": True, ...}``.
    When ``alignment["retry_recommended"]`` is true, retry the same request with
    ``search_effort="extended"``. None when the gateway sent no details.
    param: the request field the gateway rejected, such as ``"search_effort"``.
    limit_bytes: the gateway's reported size limit for ``upload_too_large``.
    """

    def __init__(self, code: str, status_code: int | None = None, *, reason: str | None = None, resets_at: str | None = None, request_id: str | None = None,
                 alignment: dict[str, Any] | None = None, param: str | None = None, limit_bytes: int | None = None,
                 upsampling: bool = False):
        self.request_id = request_id
        self.code = code
        self.status_code = status_code
        self.reason = reason or code
        self.resets_at = resets_at
        self.alignment = alignment
        self.param = param
        self.limit_bytes = limit_bytes
        guidance = {
            'audio_invalid': 'Invalid or incomplete WAV. Export a valid WAV and retry.',
            'audio_format_unsupported': 'Unsupported audio format or encoding combination. Try PCM16/24/32 or float32 WAV.',
            'audio_channels_unsupported': 'Unsupported channel count or layout. Use 1–8 channels with a valid layout.',
            # 32 MiB / 120 s are audio-upsampling limits only. Transcription and
            # alignment return the same codes with gateway-configured limits.
            'audio_too_long': ('Audio exceeds the duration limit (at most 120 seconds). Shorten the input.' if upsampling
                               else 'Audio exceeds the gateway duration limit for this request. Shorten the input.'),
            'upload_too_large': ('Audio exceeds 32 MiB. Reduce the input size.' if upsampling
                                 else 'Upload exceeds the gateway size limit'
                                 + (f' ({limit_bytes} bytes)' if limit_bytes is not None else '')
                                 + '. Reduce the input size.'),

            "unsupported_gateway_capability": "This gateway does not expose the requested API. Update the gateway runtime; updating only the SDK is insufficient.",
            "api_key_expired": f"The API KEY has expired. Create a new API KEY at {API_KEYS_URL}.",
            "api_key_revoked": f"The API KEY was revoked. Create a new API KEY at {API_KEYS_URL}.",
            "audio_upsampling_unavailable": "This CLI/gateway build does not support audio upsampling. Update the gateway runtime to a build that includes this capability.",
            "usage_exhausted": "The account allowance for this billing period is used up.",
        }.get(self.reason, f"EdgeSpeak request failed: {code}")
        if alignment is not None and alignment.get("reason"):
            guidance += f" Alignment reason: {alignment['reason']}."
        if alignment is not None and alignment.get("retry_recommended") is True:
            guidance += ' Retry with search_effort="extended".'
        super().__init__(guidance + (f" (HTTP {status_code})" if status_code else ""))


_ALIGNMENT_TOKENS = ("reason", "search_effort_used", "search_path", "search_limit")
_TOKEN = re.compile(r"[a-z0-9_]{1,64}")
_PARAM = re.compile(r"[A-Za-z0-9_.\[\]-]{1,128}")


def _alignment_details(error: dict) -> dict[str, Any] | None:
    """Keep only documented error.alignment fields whose shapes are valid."""
    value = error.get("alignment")
    if not isinstance(value, dict):
        return None
    details: dict[str, Any] = {}
    for key in _ALIGNMENT_TOKENS:
        item = value.get(key)
        if isinstance(item, str) and _TOKEN.fullmatch(item):
            details[key] = item
    if isinstance(value.get("retry_recommended"), bool):
        details["retry_recommended"] = value["retry_recommended"]
    extra = value.get("estimated_extra_bytes")
    if type(extra) is int and extra >= 0:
        details["estimated_extra_bytes"] = extra
    return details or None


def payload_error(payload: Any, status_code: int | None = None, *, upsampling: bool = False) -> EdgeSpeakError:
    code = "http_error"
    candidate = payload.get("error", {}) if isinstance(payload, dict) else None
    candidate = candidate.get("code") if isinstance(candidate, dict) else None
    if isinstance(candidate, str) and 0 < len(candidate) <= 100 and all(c.isalnum() or c in "_.-" for c in candidate):
        code = candidate
    reason, resets_at = code, None
    alignment, param, limit_bytes = None, None, None
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        alignment = _alignment_details(error)
        if isinstance(error.get("param"), str) and _PARAM.fullmatch(error["param"]):
            param = error["param"]
        if type(error.get("limit_bytes")) is int and error["limit_bytes"] > 0:
            limit_bytes = error["limit_bytes"]
        details = error
        # Existing gateway quota errors use a structured JSON message. Decode
        # only that exact schema; never expose arbitrary server message text.
        message = error.get("message")
        if code == "license_required" and isinstance(message, str) and len(message) <= 4096:
            try:
                parsed, _ = json.JSONDecoder().raw_decode(message.lstrip())
                if isinstance(parsed, dict) and parsed.get("code") == "errors.usage.exhausted":
                    reason = "usage_exhausted"
                    details = parsed.get("params", {})
            except ValueError:
                pass
        if reason == "usage_exhausted" and isinstance(details, dict):
            reset = details.get("resets_at", details.get("resetsAt"))
            if isinstance(reset, str) and len(reset) <= 40:
                try:
                    value = datetime.fromisoformat(reset.replace("Z", "+00:00"))
                    if value.tzinfo is not None:
                        resets_at = value.isoformat()
                except ValueError:
                    pass
    return EdgeSpeakError(code, status_code, reason=reason, resets_at=resets_at,
                          alignment=alignment, param=param, limit_bytes=limit_bytes, upsampling=upsampling)


def protocol_error(payload: Any, status_code: int | None = None) -> EdgeSpeakError:
    """New generation dialects: Anthropic nested type or Responses flat code.

    Keep payload_error's released transcription/alignment behavior unchanged.
    """
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        error = dict(error)
        if error.get("code") is None:
            error["code"] = error.get("type")
    else:
        error = {"code": payload.get("code"), "message": payload.get("message")} if isinstance(payload, dict) else {}
    return payload_error({"error": error}, status_code)


def check_response(response, *, gateway_api: bool = False, missing_route: bool = False, upsampling: bool = False):
    if not response.is_success:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if (gateway_api or missing_route) and response.status_code == 404 and not (
                isinstance(payload, dict) and isinstance(payload.get("error"), dict)):
            error = EdgeSpeakError("unsupported_gateway_capability", 404)
        else:
            error = protocol_error(payload, response.status_code) if gateway_api else payload_error(payload, response.status_code, upsampling=upsampling)
        request_id = response.headers.get("x-request-id", response.headers.get("request-id"))
        if request_id and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", request_id):
            error.request_id = request_id
        raise error
