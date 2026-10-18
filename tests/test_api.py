"""Tests for the eweather Firebase API client (pure client, no Home Assistant needed)."""

# The client's private helpers are the unit under test here.
# ruff: noqa: SLF001

from __future__ import annotations

import copy
import time
from typing import Any

import pytest

from custom_components.eweather.api import (
    EWeatherHomeAssistantApiClient,
    EWeatherHomeAssistantApiClientAuthenticationError,
    EWeatherHomeAssistantApiClientCommunicationError,
    EWeatherHomeAssistantApiClientError,
)
from custom_components.eweather.const import ADMIN_CACHE_TTL_SECONDS

# Sanitized fixtures based on docs/samples/*.json (no real uids/emails/tokens).
IMAGE_ORIGINAL = (
    "https://firebasestorage.googleapis.com/v0/b/e-weather-api.appspot.com/o/"
    "post%2Forigin%2FEXAMPLE_0.jpg?alt=media&token=00000000-0000-0000-0000-000000000000"
)
IMAGE_SMALL = (
    "https://firebasestorage.googleapis.com/v0/b/e-weather-api.appspot.com/o/"
    "post%2Fsmall%2FEXAMPLE_0.jpg?alt=media&token=00000000-0000-0000-0000-000000000000"
)

# Decoded posts as _firestore_run_query would return them (pre-tagging).
OFFICIAL_POST: dict[str, Any] = {
    "__doc_id__": "EXAMPLE_OFFICIAL_POST",
    "sender": "ADMIN_UID_EXAMPLE",
    "category": "weather",
    "title": "A dangerous and prolonged heat wave begins today.",
    "text": "Stay hydrated and check on neighbors.",
    "created": "2026-07-02T12:46:10.712566Z",
    "images": [
        {
            "original": IMAGE_ORIGINAL,
            "small": IMAGE_SMALL,
            "isVideo": False,
            "ratio": 0.75,
            "created": "2026-07-02T12:46:10.712566Z",
        },
    ],
    "likes": 46,
    "comments": 2,
    "views": 312,
    "notification": False,
}

USER_POST: dict[str, Any] = {
    "__doc_id__": "EXAMPLE_USER_POST",
    "sender": "USER_UID_EXAMPLE",
    "category": "topPhotos",
    "title": "Beautiful lake at sunset - Example Town",
    "created": "2025-06-23T15:11:07.640399Z",
    "sharePhoto": True,
    "images": [
        {
            "original": IMAGE_ORIGINAL,
            "small": IMAGE_SMALL,
            "isVideo": False,
            "ratio": 0.75,
        },
    ],
    "likes": 25,
    "comments": 0,
    "views": 1405,
    "notification": False,
}

ADMIN_DOCS: list[dict[str, Any]] = [{"__doc_id__": "ADMIN_UID_EXAMPLE", "name": "eweather"}]


@pytest.fixture
def client() -> EWeatherHomeAssistantApiClient:
    """Return a client whose HTTP layer is expected to be stubbed out."""
    return EWeatherHomeAssistantApiClient(
        username="user@example.com",
        password="hunter2-example",
        session=None,  # type: ignore[arg-type]  # every test stubs the transport
    )


def _stub_send(
    monkeypatch: pytest.MonkeyPatch,
    client: EWeatherHomeAssistantApiClient,
    responses: dict[str, tuple[int, Any]],
) -> list[tuple[str, str, dict[str, Any] | None]]:
    """Replace ``client._send`` with canned ``(status, body)`` responses keyed by URL substring."""
    calls: list[tuple[str, str, dict[str, Any] | None]] = []

    async def fake_send(
        method: str,
        url: str,
        *,
        json_body: dict[str, Any] | None = None,
        form_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, Any]:
        calls.append((method, url, json_body if json_body is not None else form_body))
        key = next((candidate for candidate in responses if candidate in url), None)
        assert key is not None, f"Unexpected URL requested: {url}"
        return responses[key]

    monkeypatch.setattr(client, "_send", fake_send)
    return calls


def _stub_queries(
    monkeypatch: pytest.MonkeyPatch,
    client: EWeatherHomeAssistantApiClient,
    *,
    admin_docs: list[dict[str, Any]],
    post_docs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Stub the Firestore queries (and token check) with decoded sample docs."""
    queries: list[dict[str, Any]] = []

    async def fake_run_query(structured_query: dict[str, Any]) -> list[dict[str, Any]]:
        queries.append(structured_query)
        collection = structured_query["from"][0]["collectionId"]
        if collection == "User":
            return copy.deepcopy(admin_docs)
        assert collection == "Post"
        return copy.deepcopy(post_docs)

    async def fake_ensure_token() -> None:
        return None

    monkeypatch.setattr(client, "_firestore_run_query", fake_run_query)
    monkeypatch.setattr(client, "_ensure_token", fake_ensure_token)
    return queries


# -- _decode_value / _decode_document ----------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"stringValue": "hello"}, "hello"),
        ({"integerValue": "42"}, 42),
        ({"integerValue": 7}, 7),
        ({"integerValue": "not-a-number"}, "not-a-number"),
        ({"doubleValue": 0.75}, 0.75),
        ({"booleanValue": True}, True),
        ({"booleanValue": False}, False),
        (
            {"timestampValue": "2026-07-02T12:46:10.712566Z"},
            "2026-07-02T12:46:10.712566Z",
        ),
        ({"nullValue": None}, None),
        (
            {"referenceValue": "projects/e-weather-api/databases/(default)/documents/User/ADMIN_UID_EXAMPLE"},
            "projects/e-weather-api/databases/(default)/documents/User/ADMIN_UID_EXAMPLE",
        ),
        (
            {"geoPointValue": {"latitude": 40.7, "longitude": -74.0}},
            {"latitude": 40.7, "longitude": -74.0},
        ),
    ],
)
def test_decode_value_scalars(value: dict[str, Any], expected: Any) -> None:
    assert EWeatherHomeAssistantApiClient._decode_value(value) == expected


def test_decode_value_array() -> None:
    value = {
        "arrayValue": {
            "values": [
                {"stringValue": "a"},
                {"integerValue": "1"},
                {"arrayValue": {"values": [{"booleanValue": True}]}},
            ],
        },
    }
    assert EWeatherHomeAssistantApiClient._decode_value(value) == ["a", 1, [True]]


def test_decode_value_empty_array() -> None:
    assert EWeatherHomeAssistantApiClient._decode_value({"arrayValue": {}}) == []


def test_decode_value_map() -> None:
    value = {
        "mapValue": {
            "fields": {
                "original": {"stringValue": IMAGE_ORIGINAL},
                "isVideo": {"booleanValue": False},
                "ratio": {"doubleValue": 0.75},
                "nested": {"mapValue": {"fields": {"n": {"integerValue": "5"}}}},
            },
        },
    }
    assert EWeatherHomeAssistantApiClient._decode_value(value) == {
        "original": IMAGE_ORIGINAL,
        "isVideo": False,
        "ratio": 0.75,
        "nested": {"n": 5},
    }


def test_decode_value_empty_map() -> None:
    assert EWeatherHomeAssistantApiClient._decode_value({"mapValue": {}}) == {}


def test_decode_value_unknown_type_returned_unchanged() -> None:
    value = {"bytesValue": "AAAA"}
    assert EWeatherHomeAssistantApiClient._decode_value(value) is value


def test_decode_document_extracts_fields_and_doc_id() -> None:
    doc = {
        "name": "projects/e-weather-api/databases/(default)/documents/Post/EXAMPLE_OFFICIAL_POST",
        "fields": {
            "sender": {"stringValue": "ADMIN_UID_EXAMPLE"},
            "category": {"stringValue": "weather"},
            "title": {"stringValue": "A dangerous and prolonged heat wave begins today."},
            "text": {"stringValue": "Stay hydrated and check on neighbors."},
            "created": {"timestampValue": "2026-07-02T12:46:10.712566Z"},
            "likes": {"integerValue": "46"},
            "comments": {"integerValue": "2"},
            "views": {"integerValue": "312"},
            "notification": {"booleanValue": False},
            "images": {
                "arrayValue": {
                    "values": [
                        {
                            "mapValue": {
                                "fields": {
                                    "original": {"stringValue": IMAGE_ORIGINAL},
                                    "small": {"stringValue": IMAGE_SMALL},
                                    "isVideo": {"booleanValue": False},
                                    "ratio": {"doubleValue": 0.75},
                                    "created": {"timestampValue": "2026-07-02T12:46:10.712566Z"},
                                },
                            },
                        },
                    ],
                },
            },
        },
    }
    assert EWeatherHomeAssistantApiClient._decode_document(doc) == OFFICIAL_POST


def test_decode_document_without_name_has_empty_doc_id() -> None:
    decoded = EWeatherHomeAssistantApiClient._decode_document({"fields": {"a": {"integerValue": "1"}}})
    assert decoded == {"a": 1, "__doc_id__": ""}


def test_decode_document_non_string_name_yields_none_doc_id() -> None:
    decoded = EWeatherHomeAssistantApiClient._decode_document({"name": 123, "fields": {}})
    assert decoded == {"__doc_id__": None}


# -- _error_code --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"error": {"message": "INVALID_PASSWORD"}}, "INVALID_PASSWORD"),
        (
            {
                "error": {
                    "message": "TOO_MANY_ATTEMPTS_TRY_LATER : Access to this account has been temporarily disabled."
                }
            },
            "TOO_MANY_ATTEMPTS_TRY_LATER",
        ),
        ({"error": {"message": "QUOTA_EXCEEDED: too much"}}, "QUOTA_EXCEEDED"),
        ({"error": {"message": "   "}}, ""),
        ({"error": {"message": None}}, ""),
        ({"error": "broken"}, ""),
        ({}, ""),
        ("Service Unavailable", ""),
        (None, ""),
    ],
)
def test_error_code(data: Any, expected: str) -> None:
    assert EWeatherHomeAssistantApiClient._error_code(data) == expected


# -- _sign_in classification ---------------------------------------------------------


async def test_sign_in_success_stores_tokens(
    client: EWeatherHomeAssistantApiClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_send(
        monkeypatch,
        client,
        {
            "signInWithPassword": (
                200,
                {
                    "idToken": "id-token-example",
                    "refreshToken": "refresh-token-example",
                    "expiresIn": "3600",
                    "localId": "UID_EXAMPLE",
                },
            ),
        },
    )
    await client._sign_in()
    assert client._id_token == "id-token-example"
    assert client._refresh_token == "refresh-token-example"
    assert client._uid == "UID_EXAMPLE"
    # Expiry is monotonic + 3600 minus the 60 s safety margin.
    assert time.monotonic() < client._token_expiry <= time.monotonic() + 3540


async def test_sign_in_invalid_password_raises_authentication_error(
    client: EWeatherHomeAssistantApiClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_send(
        monkeypatch,
        client,
        {"signInWithPassword": (400, {"error": {"message": "INVALID_PASSWORD"}})},
    )
    with pytest.raises(EWeatherHomeAssistantApiClientAuthenticationError):
        await client._sign_in()


async def test_sign_in_rate_limited_raises_communication_error(
    client: EWeatherHomeAssistantApiClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rate-limit response must NOT look like bad credentials (no reauth prompt)."""
    _stub_send(
        monkeypatch,
        client,
        {
            "signInWithPassword": (
                400,
                {
                    "error": {
                        "message": "TOO_MANY_ATTEMPTS_TRY_LATER : Access to this account has been temporarily disabled."
                    }
                },
            ),
        },
    )
    with pytest.raises(EWeatherHomeAssistantApiClientCommunicationError):
        await client._sign_in()


async def test_sign_in_server_error_raises_communication_error(
    client: EWeatherHomeAssistantApiClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 5xx with a non-JSON body is transient, not an auth failure."""
    _stub_send(monkeypatch, client, {"signInWithPassword": (503, "Service Unavailable")})
    with pytest.raises(EWeatherHomeAssistantApiClientCommunicationError):
        await client._sign_in()


async def test_sign_in_unknown_code_raises_base_error(
    client: EWeatherHomeAssistantApiClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_send(
        monkeypatch,
        client,
        {"signInWithPassword": (400, {"error": {"message": "SOMETHING_UNEXPECTED"}})},
    )
    with pytest.raises(EWeatherHomeAssistantApiClientError) as excinfo:
        await client._sign_in()
    assert type(excinfo.value) is EWeatherHomeAssistantApiClientError


# -- Token refresh -------------------------------------------------------------------


async def test_refresh_success_updates_tokens(
    client: EWeatherHomeAssistantApiClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client._refresh_token = "refresh-token-example"
    calls = _stub_send(
        monkeypatch,
        client,
        {
            "securetoken": (
                200,
                {
                    "id_token": "fresh-id-token",
                    "refresh_token": "fresh-refresh-token",
                    "expires_in": "3600",
                    "user_id": "UID_EXAMPLE",
                },
            ),
        },
    )
    await client._refresh()
    assert client._id_token == "fresh-id-token"
    assert client._refresh_token == "fresh-refresh-token"
    assert client._uid == "UID_EXAMPLE"
    assert len(calls) == 1


async def test_refresh_failure_falls_back_to_sign_in(
    client: EWeatherHomeAssistantApiClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rejected refresh token is dropped and a fresh sign-in is performed."""
    client._refresh_token = "stale-refresh-token"
    calls = _stub_send(
        monkeypatch,
        client,
        {
            "securetoken": (400, {"error": {"message": "TOKEN_EXPIRED"}}),
            "signInWithPassword": (
                200,
                {
                    "idToken": "new-id-token",
                    "refreshToken": "new-refresh-token",
                    "expiresIn": "3600",
                    "localId": "UID_EXAMPLE",
                },
            ),
        },
    )
    await client._refresh()
    assert client._id_token == "new-id-token"
    assert client._refresh_token == "new-refresh-token"
    urls = [url for _, url, _ in calls]
    assert len(urls) == 2
    assert "securetoken" in urls[0]
    assert "signInWithPassword" in urls[1]


async def test_ensure_token_skips_auth_when_token_fresh(
    client: EWeatherHomeAssistantApiClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client._id_token = "cached-token"
    client._token_expiry = time.monotonic() + 1000

    async def fail() -> None:
        raise AssertionError("must not re-authenticate while the token is fresh")

    monkeypatch.setattr(client, "_refresh_or_sign_in", fail)
    await client._ensure_token()


# -- async_get_data / filtering -------------------------------------------------------


async def test_async_get_data_tags_sorts_and_counts(
    client: EWeatherHomeAssistantApiClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Posts intentionally oldest-first to prove the newest-first re-sort.
    _stub_queries(monkeypatch, client, admin_docs=ADMIN_DOCS, post_docs=[USER_POST, OFFICIAL_POST])

    data = await client.async_get_data()

    assert [post["__doc_id__"] for post in data["posts"]] == [
        "EXAMPLE_OFFICIAL_POST",
        "EXAMPLE_USER_POST",
    ]
    official_post, user_post = data["posts"]
    assert official_post["_official"] is True
    assert official_post["_author"] == "eweather"
    assert user_post["_official"] is False
    assert "_author" not in user_post
    assert [post["__doc_id__"] for post in data["official"]] == ["EXAMPLE_OFFICIAL_POST"]
    assert data["counts"] == {"total": 2, "official": 1}


async def test_async_get_data_admin_name_falls_back_to_uid(
    client: EWeatherHomeAssistantApiClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_queries(
        monkeypatch,
        client,
        admin_docs=[{"__doc_id__": "ADMIN_UID_EXAMPLE"}],  # no name on the User doc
        post_docs=[OFFICIAL_POST],
    )
    data = await client.async_get_data()
    assert data["posts"][0]["_author"] == "ADMIN_UID_EXAMPLE"


def test_filter_official(client: EWeatherHomeAssistantApiClient) -> None:
    posts = [copy.deepcopy(OFFICIAL_POST), copy.deepcopy(USER_POST)]
    assert client.filter_official(posts, {"ADMIN_UID_EXAMPLE"}) == [posts[0]]
    assert client.filter_official(posts, set()) == []
    assert client.filter_official([], {"ADMIN_UID_EXAMPLE"}) == []


# -- Admin cache TTL ------------------------------------------------------------------


async def test_admin_cache_ttl(
    client: EWeatherHomeAssistantApiClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queries = _stub_queries(monkeypatch, client, admin_docs=ADMIN_DOCS, post_docs=[])

    admins = await client._get_admins()
    assert admins == {"ADMIN_UID_EXAMPLE": "eweather"}
    assert len(queries) == 1
    # The cache expiry is stamped one TTL into the future.
    assert client._admin_cache_expiry == pytest.approx(time.monotonic() + ADMIN_CACHE_TTL_SECONDS, abs=5.0)

    # Within the TTL the cache is served without another query.
    assert await client._get_admins() == admins
    assert len(queries) == 1

    # Once the TTL elapses the admin map is re-fetched.
    client._admin_cache_expiry = time.monotonic() - 1
    assert await client._get_admins() == admins
    assert len(queries) == 2


async def test_admin_cache_kept_on_transient_empty_result(
    client: EWeatherHomeAssistantApiClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_queries(monkeypatch, client, admin_docs=ADMIN_DOCS, post_docs=[])
    assert await client._get_admins() == {"ADMIN_UID_EXAMPLE": "eweather"}

    # Expire the cache, then have the backend return no admins: keep the old map.
    client._admin_cache_expiry = time.monotonic() - 1

    async def empty_query(structured_query: dict[str, Any]) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr(client, "_firestore_run_query", empty_query)
    assert await client._get_admins() == {"ADMIN_UID_EXAMPLE": "eweather"}
