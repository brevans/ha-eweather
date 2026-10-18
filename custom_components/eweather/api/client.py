"""
API client for eweather — Firebase backend.

The eweather app stores its forecast feed in Cloud Firestore behind Firebase Auth
(email/password). This client:

1. Signs in with the user's email/password (Firebase Auth REST) and caches the
   ID token, refreshing it via the secure-token endpoint before it expires.
2. Reads the newest ``Post`` documents over the Firestore REST API and decodes the
   typed values into plain dicts.
3. Keeps only official eweather posts. Official posts are those whose author
   (``sender`` uid) is an admin account — determined by ``admin == true`` on the
   author's ``User`` document. The admin uid set is fetched with one filtered query
   and cached.

See ``docs/API_CONTRACT.md`` for the full contract.
"""

from __future__ import annotations

import asyncio
import socket
import time
from typing import Any

import aiohttp

from custom_components.eweather.const import (
    ADMIN_CACHE_TTL_SECONDS,
    DEFAULT_FETCH_LIMIT,
    FIREBASE_API_KEY,
    FIREBASE_AUTH_URL,
    FIREBASE_TOKEN_URL,
    FIRESTORE_URL,
    LOGGER,
    POST_COLLECTION,
    POST_SENDER_FIELD,
    POST_TIMESTAMP_FIELD,
    USER_ADMIN_FIELD,
    USER_COLLECTION,
    USER_NAME_FIELD,
)

# Firebase Auth error codes that mean "bad credentials", not a transient fault.
_AUTH_ERROR_CODES = frozenset(
    {
        "EMAIL_NOT_FOUND",
        "INVALID_PASSWORD",
        "INVALID_LOGIN_CREDENTIALS",
        "USER_DISABLED",
        "USER_NOT_FOUND",
        "INVALID_EMAIL",
        "MISSING_PASSWORD",
    },
)

# Firebase Auth error codes for transient conditions that should be retried later.
_TRANSIENT_ERROR_CODES = frozenset(
    {
        "TOO_MANY_ATTEMPTS_TRY_LATER",
        "QUOTA_EXCEEDED",
    },
)

# Refresh the ID token this many seconds before its stated expiry.
_TOKEN_REFRESH_MARGIN = 60

# Internal keys the client attaches to decoded posts.
_DOC_ID_KEY = "__doc_id__"
_OFFICIAL_KEY = "_official"
_AUTHOR_KEY = "_author"


class EWeatherHomeAssistantApiClientError(Exception):
    """Base exception to indicate a general API error."""


class EWeatherHomeAssistantApiClientCommunicationError(
    EWeatherHomeAssistantApiClientError,
):
    """Exception to indicate a communication error with the API."""


class EWeatherHomeAssistantApiClientAuthenticationError(
    EWeatherHomeAssistantApiClientError,
):
    """Exception to indicate an authentication error with the API."""


class EWeatherHomeAssistantApiClient:
    """Client for the eweather Firebase backend.

    Handles Firebase Auth (email/password) with token caching/refresh and reads the
    forecast feed from Cloud Firestore. Credentials come from the config flow; the
    ``username`` field holds the account email.
    """

    def __init__(
        self,
        username: str,
        password: str,
        session: aiohttp.ClientSession,
    ) -> None:
        """Initialize the client.

        Args:
            username: The account email (config flow stores it as the username).
            password: The account password.
            session: The aiohttp ClientSession to use for requests.
        """
        self._username = username
        self._password = password
        self._session = session
        self._id_token: str | None = None
        self._refresh_token: str | None = None
        self._uid: str | None = None
        self._token_expiry: float = 0.0
        # Cache of official-author uid -> display name.
        self._admin_map: dict[str, str] = {}
        self._admin_cache_expiry: float = 0.0

    # -- Public API ---------------------------------------------------------------

    async def async_get_data(self) -> dict[str, Any]:
        """Authenticate if needed, fetch the newest posts, and tag official ones.

        Returns:
            A dict with ``posts`` (all fetched, newest first, each tagged with an
            internal ``_official`` flag and, for official posts, an ``_author`` name),
            ``official`` (the official subset), and ``counts``.

        Raises:
            EWeatherHomeAssistantApiClientAuthenticationError: If sign-in fails.
            EWeatherHomeAssistantApiClientCommunicationError: If the network fails.
            EWeatherHomeAssistantApiClientError: For other API errors.
        """
        await self._ensure_token()
        admins = await self._get_admins()
        posts = await self._fetch_recent_posts(DEFAULT_FETCH_LIMIT)

        for post in posts:
            sender = post.get(POST_SENDER_FIELD)
            if isinstance(sender, str) and sender in admins:
                post[_OFFICIAL_KEY] = True
                post[_AUTHOR_KEY] = admins[sender]
            else:
                post[_OFFICIAL_KEY] = False

        posts.sort(key=self._post_sort_key, reverse=True)
        official = [post for post in posts if post[_OFFICIAL_KEY]]
        LOGGER.debug(
            "Fetched %d posts (%d official) from %d admin authors",
            len(posts),
            len(official),
            len(admins),
        )
        return {
            "posts": posts,
            "official": official,
            "counts": {"total": len(posts), "official": len(official)},
        }

    async def async_validate_credentials(self) -> None:
        """Prove the credentials work by signing in (no feed fetch).

        Raises:
            EWeatherHomeAssistantApiClientAuthenticationError: If the credentials are bad.
            EWeatherHomeAssistantApiClientCommunicationError: If the backend is unreachable.
            EWeatherHomeAssistantApiClientError: For other API errors.
        """
        await self._ensure_token()

    def filter_official(
        self,
        posts: list[dict[str, Any]],
        admin_uids: set[str],
    ) -> list[dict[str, Any]]:
        """Return only the official eweather posts (author uid is an admin)."""
        return [post for post in posts if post.get(POST_SENDER_FIELD) in admin_uids]

    # -- Firestore reads ----------------------------------------------------------

    async def _get_admins(self) -> dict[str, str]:
        """Return the {uid: name} map of official (admin) authors, cached.

        Queries ``User`` for ``admin == true`` (a single-field equality filter, so no
        composite index is required). A transient empty result keeps the prior cache.
        """
        if self._admin_map and time.monotonic() < self._admin_cache_expiry:
            return self._admin_map

        query = {
            "from": [{"collectionId": USER_COLLECTION}],
            "where": {
                "fieldFilter": {
                    "field": {"fieldPath": USER_ADMIN_FIELD},
                    "op": "EQUAL",
                    "value": {"booleanValue": True},
                },
            },
        }
        docs = await self._firestore_run_query(query)
        admins: dict[str, str] = {}
        for doc in docs:
            uid = doc.get(_DOC_ID_KEY)
            if isinstance(uid, str) and uid:
                name = doc.get(USER_NAME_FIELD)
                admins[uid] = name if isinstance(name, str) and name else uid

        if admins:
            self._admin_map = admins
            self._admin_cache_expiry = time.monotonic() + ADMIN_CACHE_TTL_SECONDS
        return self._admin_map

    async def _fetch_recent_posts(self, limit: int) -> list[dict[str, Any]]:
        """Fetch the newest posts, ordered by creation time (newest first)."""
        query = {
            "from": [{"collectionId": POST_COLLECTION}],
            "orderBy": [{"field": {"fieldPath": POST_TIMESTAMP_FIELD}, "direction": "DESCENDING"}],
            "limit": limit,
        }
        return await self._firestore_run_query(query)

    async def _firestore_run_query(self, structured_query: dict[str, Any]) -> list[dict[str, Any]]:
        """Run a Firestore ``runQuery`` and return the decoded documents."""
        url = f"{FIRESTORE_URL}:runQuery"
        body = {"structuredQuery": structured_query}
        await self._ensure_token()
        status, data = await self._send("POST", url, json_body=body, headers=self._auth_headers())
        if status in (401, 403):
            await self._refresh_or_sign_in()
            status, data = await self._send("POST", url, json_body=body, headers=self._auth_headers())

        if status == 200 and isinstance(data, list):
            return [
                self._decode_document(item["document"])
                for item in data
                if isinstance(item, dict) and "document" in item
            ]
        if status in (401, 403):
            msg = "Not authorized to query Firestore"
            raise EWeatherHomeAssistantApiClientAuthenticationError(msg)
        msg = f"Firestore runQuery returned {status}"
        raise EWeatherHomeAssistantApiClientError(msg)

    def _auth_headers(self) -> dict[str, str]:
        """Return the Firestore authorization header for the current token."""
        return {"Authorization": f"Bearer {self._id_token}"}

    @staticmethod
    def _post_sort_key(post: dict[str, Any]) -> str:
        """Return a sortable key (newest wins with reverse sort) from ``created``."""
        value = post.get(POST_TIMESTAMP_FIELD)
        return str(value) if value else ""

    # -- Firebase Auth ------------------------------------------------------------

    async def _ensure_token(self) -> None:
        """Ensure a non-expired ID token is available, signing in or refreshing."""
        if self._id_token and time.monotonic() < self._token_expiry:
            return
        await self._refresh_or_sign_in()

    async def _refresh_or_sign_in(self) -> None:
        """Refresh the token if we have a refresh token, otherwise sign in fresh."""
        if self._refresh_token:
            await self._refresh()
        else:
            await self._sign_in()

    async def _sign_in(self) -> None:
        """Sign in with email/password via the Firebase Auth REST API."""
        url = f"{FIREBASE_AUTH_URL}/accounts:signInWithPassword?key={FIREBASE_API_KEY}"
        status, data = await self._send(
            "POST",
            url,
            json_body={
                "email": self._username,
                "password": self._password,
                "returnSecureToken": True,
            },
        )
        if status == 200 and isinstance(data, dict) and "idToken" in data:
            self._store_tokens(data["idToken"], data.get("refreshToken"), data.get("expiresIn"))
            self._uid = data.get("localId")
            return

        # Only genuine credential errors may raise the authentication exception: the
        # coordinator turns it into a reauth prompt, which must not fire for backend
        # hiccups (5xx, rate limiting) — those must stay retryable.
        code = self._error_code(data)
        if code in _AUTH_ERROR_CODES:
            msg = f"Invalid credentials ({code})"
            raise EWeatherHomeAssistantApiClientAuthenticationError(msg)
        if status >= 500 or status == 429 or code in _TRANSIENT_ERROR_CODES:
            msg = f"Sign-in temporarily unavailable ({code or status})"
            raise EWeatherHomeAssistantApiClientCommunicationError(msg)
        msg = f"Unexpected sign-in response ({code or status})"
        raise EWeatherHomeAssistantApiClientError(msg)

    async def _refresh(self) -> None:
        """Exchange the refresh token for a fresh ID token; fall back to sign-in."""
        url = f"{FIREBASE_TOKEN_URL}?key={FIREBASE_API_KEY}"
        status, data = await self._send(
            "POST",
            url,
            form_body={"grant_type": "refresh_token", "refresh_token": self._refresh_token},
        )
        if status != 200 or not isinstance(data, dict) or "id_token" not in data:
            LOGGER.debug("Token refresh failed (status %s); signing in again", status)
            self._refresh_token = None
            await self._sign_in()
            return
        self._store_tokens(data["id_token"], data.get("refresh_token"), data.get("expires_in"))
        self._uid = data.get("user_id", self._uid)

    def _store_tokens(self, id_token: str, refresh_token: Any, expires_in: Any) -> None:
        """Cache the ID/refresh tokens and compute the expiry with a safety margin."""
        self._id_token = id_token
        if isinstance(refresh_token, str) and refresh_token:
            self._refresh_token = refresh_token
        try:
            ttl = int(expires_in)
        except TypeError, ValueError:
            ttl = 3600
        self._token_expiry = time.monotonic() + max(ttl - _TOKEN_REFRESH_MARGIN, 0)

    @staticmethod
    def _error_code(data: Any) -> str:
        """Extract the Firebase error code from an error payload.

        Firebase sometimes appends detail after the code, e.g.
        ``TOO_MANY_ATTEMPTS_TRY_LATER : Access to this account has been ...``.
        """
        if isinstance(data, dict):
            error = data.get("error")
            if isinstance(error, dict):
                message = error.get("message")
                if isinstance(message, str):
                    parts = message.split()
                    if parts:
                        return parts[0].rstrip(":")
        return ""

    # -- HTTP + Firestore decoding ------------------------------------------------

    async def _send(
        self,
        method: str,
        url: str,
        *,
        json_body: dict[str, Any] | None = None,
        form_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, Any]:
        """Send a request and return ``(status, decoded_body)``, mapping I/O errors."""
        try:
            async with asyncio.timeout(30):
                response = await self._session.request(
                    method=method,
                    url=url,
                    json=json_body,
                    data=form_body,
                    headers=headers,
                )
                try:
                    payload: Any = await response.json(content_type=None)
                except aiohttp.ContentTypeError, ValueError:
                    payload = await response.text()
                return response.status, payload
        except TimeoutError as exception:
            msg = f"Timeout error contacting the eweather backend - {exception}"
            raise EWeatherHomeAssistantApiClientCommunicationError(msg) from exception
        except (aiohttp.ClientError, socket.gaierror) as exception:
            msg = f"Error contacting the eweather backend - {exception}"
            raise EWeatherHomeAssistantApiClientCommunicationError(msg) from exception

    @classmethod
    def _decode_document(cls, doc: dict[str, Any]) -> dict[str, Any]:
        """Decode a Firestore document into a plain dict with its id under ``__doc_id__``."""
        fields = {key: cls._decode_value(value) for key, value in doc.get("fields", {}).items()}
        name = doc.get("name", "")
        fields[_DOC_ID_KEY] = name.rsplit("/", 1)[-1] if isinstance(name, str) else None
        return fields

    @classmethod
    def _decode_value(cls, value: dict[str, Any]) -> Any:
        """Convert one Firestore typed value into a plain Python value."""
        if "stringValue" in value:
            return value["stringValue"]
        if "integerValue" in value:
            try:
                return int(value["integerValue"])
            except TypeError, ValueError:
                return value["integerValue"]
        if "doubleValue" in value:
            return value["doubleValue"]
        if "booleanValue" in value:
            return value["booleanValue"]
        if "timestampValue" in value:
            return value["timestampValue"]
        if "nullValue" in value:
            return None
        if "referenceValue" in value:
            return value["referenceValue"]
        if "geoPointValue" in value:
            return value["geoPointValue"]
        if "arrayValue" in value:
            return [cls._decode_value(item) for item in value["arrayValue"].get("values", [])]
        if "mapValue" in value:
            return {key: cls._decode_value(item) for key, item in value["mapValue"].get("fields", {}).items()}
        return value
