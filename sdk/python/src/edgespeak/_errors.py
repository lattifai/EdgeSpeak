"""Stable, content-free errors shared by ordinary and streaming responses."""
from typing import Any
from datetime import datetime
import json


API_KEYS_URL = "https://edgespeak.com/account/api-keys"


class EdgeSpeakError(RuntimeError):
    """A gateway failure, with a stable code and optional HTTP status."""

    def __init__(self, code: str, status_code: int | None = None, *, reason: str | None = None, resets_at: str | None = None):
        self.code = code
        self.status_code = status_code
        self.reason = reason or code
        self.resets_at = resets_at
        guidance = {
            "api_key_expired": f"The API KEY has expired. Create a new API KEY at {API_KEYS_URL}.",
            "api_key_revoked": f"The API KEY was revoked. Create a new API KEY at {API_KEYS_URL}.",
            "usage_exhausted": "The account allowance for this billing period is used up.",
        }.get(self.reason, f"EdgeSpeak request failed: {code}")
        super().__init__(guidance + (f" (HTTP {status_code})" if status_code else ""))


def payload_error(payload: Any, status_code: int | None = None) -> EdgeSpeakError:
    code = "http_error"
    candidate = payload.get("error", {}) if isinstance(payload, dict) else None
    candidate = candidate.get("code") if isinstance(candidate, dict) else None
    if isinstance(candidate, str) and 0 < len(candidate) <= 100 and all(c.isalnum() or c in "_.-" for c in candidate):
        code = candidate
    reason, resets_at = code, None
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
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
    return EdgeSpeakError(code, status_code, reason=reason, resets_at=resets_at)


def check_response(response):
    if not response.is_success:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        raise payload_error(payload, response.status_code)
