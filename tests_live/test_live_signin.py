"""Live smoke test against the real eweather Firebase backend.

This test is intentionally OUTSIDE the default ``tests/`` tree (``testpaths`` in
pyproject.toml), so ``script/test`` and the normal CI never run it. It is run only
by the ``Live smoke`` workflow (and manually), because it needs real credentials
and makes real network calls to eweather's backend.

Run locally:

    EWEATHER_USERNAME=you@example.com EWEATHER_PASSWORD=... \\
        pytest tests_live/ -v

It skips itself when the credentials are not in the environment, so an accidental
``pytest tests_live/`` without secrets is a skip, not a failure.

On failure it re-queries the sign-in endpoint (exactly as the client does, with no
extra headers) purely to read Google's own error payload, so the CI log names the
precise Firebase reason — e.g. ``API_KEY_ANDROID_APP_BLOCKED`` — instead of only the
first word the integration keeps. Credentials go only into the request body; nothing
secret is ever printed.
"""

from __future__ import annotations

import os

import aiohttp
import pytest

from custom_components.eweather.api import EWeatherHomeAssistantApiClient, EWeatherHomeAssistantApiClientError
from custom_components.eweather.const import FIREBASE_API_KEY, FIREBASE_AUTH_URL

pytestmark = pytest.mark.live

_USERNAME = os.environ.get("EWEATHER_USERNAME", "")
_PASSWORD = os.environ.get("EWEATHER_PASSWORD", "")

_SKIP_REASON = "EWEATHER_USERNAME / EWEATHER_PASSWORD not set — live credentials required"


async def _firebase_sign_in_reason(session: aiohttp.ClientSession) -> str:
    """Return a human-readable Firebase error for the current credentials.

    Hits the same ``signInWithPassword`` endpoint the client uses, with no added
    headers, and extracts ``error.status`` / ``details[].reason`` / ``error.message``.
    Used only to annotate a failure; it reveals why the backend rejected us
    (bad password vs. a blocked API key vs. an outage) without printing secrets.
    """
    url = f"{FIREBASE_AUTH_URL}/accounts:signInWithPassword?key={FIREBASE_API_KEY}"
    body = {"email": _USERNAME, "password": _PASSWORD, "returnSecureToken": True}
    try:
        async with session.post(url, json=body) as response:
            status = response.status
            payload = await response.json(content_type=None)
    except aiohttp.ClientError as exc:  # pragma: no cover - network-dependent
        return f"could not reach sign-in endpoint: {exc}"

    if not isinstance(payload, dict):
        return f"HTTP {status}; non-JSON response"
    error = payload.get("error")
    if not isinstance(error, dict):
        return f"HTTP {status}; no error object (sign-in may have succeeded)"
    reasons = [
        detail["reason"] for detail in error.get("details", []) if isinstance(detail, dict) and detail.get("reason")
    ]
    return (
        f"HTTP {status} | status={error.get('status')} | "
        f"reasons={reasons or ['<none>']} | message={error.get('message')!r}"
    )


@pytest.mark.skipif(not (_USERNAME and _PASSWORD), reason=_SKIP_REASON)
async def test_live_sign_in_and_fetch() -> None:
    """Sign in and fetch the feed from the live backend; fail with the Firebase reason."""
    async with aiohttp.ClientSession() as session:
        client = EWeatherHomeAssistantApiClient(_USERNAME, _PASSWORD, session)
        try:
            data = await client.async_get_data()
        except EWeatherHomeAssistantApiClientError as exc:
            reason = await _firebase_sign_in_reason(session)
            pytest.fail(f"Live eweather request failed: {exc}\nFirebase sign-in diagnostic: {reason}")

    counts = data["counts"]
    print(f"Live fetch OK: {counts['total']} posts, {counts['official']} official")
    assert isinstance(data["posts"], list)
    assert counts["total"] >= 1, "authenticated, but the feed returned zero posts"
