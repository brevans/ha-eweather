#!/usr/bin/env python3
"""Local discovery probe for the eweather Firebase backend (Milestone 1, Part B).

The eweather Android app (``com.saybrook.eweather_mobile``) is a Flutter app whose
backend is Firebase. Static analysis of the APK gave us the project config and the
data model (a Firestore ``Post`` collection). This script signs in with a *real*
account and reads the live data so we can lock the JSON schema and — most
importantly — discover exactly how OFFICIAL eweather posts are distinguished from
USER-submitted posts.

Everything here uses only the Python standard library, so it runs anywhere with
Python 3.9+ and needs no ``pip install``.

Usage
-----
1. Create a throwaway eweather account in the app (email/password sign-up).
2. Copy ``.env.example`` to ``.env`` in the repo root and fill in the credentials.
   ``.env`` is git-ignored — never commit real credentials.
3. Run from the repo root::

       python3 tools/probe.py

   It prints the auth flow, the discovered collection(s), the union of field names,
   and candidate official-vs-user discriminators, then writes redacted sample
   documents to ``docs/samples/``.

SECURITY
--------
- Reads credentials from ``.env`` / environment only. Never hardcode them.
- Redacts obvious secrets (tokens, emails, device/FCM tokens, coordinates) before
  writing samples, but you MUST still review ``docs/samples/*.json`` and remove any
  remaining PII from other users before committing them as test fixtures.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Any
import urllib.error
import urllib.request

# --- Firebase config (from static APK analysis; see docs/API_CONTRACT.md) -------
API_KEY = "AIzaSyAWiIO_KEeAyBDhwu6wfnQ8cgM--RJhKPg"
PROJECT_ID = "e-weather-api"
DATABASE_URL = "https://e-weather-api-default-rtdb.firebaseio.com"

IDENTITY_TOOLKIT = "https://identitytoolkit.googleapis.com/v1"
FIRESTORE = f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/(default)/documents"

# Collection-name candidates to probe (Firestore IDs are case-sensitive; static
# analysis surfaced both "Post" and "post"). First one that returns docs wins.
POST_COLLECTION_CANDIDATES = ["Post", "post", "Posts", "posts"]
OTHER_COLLECTIONS = ["PostStaging", "staging", "Alerts", "Alert", "alerts"]

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = REPO_ROOT / "docs" / "samples"

# Fields to redact from any saved sample document.
REDACT_FIELDS = {
    "email",
    "password",
    "phone",
    "phoneNumber",
    "fcmToken",
    "deviceToken",
    "token",
    "idToken",
    "refreshToken",
    "latitude",
    "longitude",
    "lat",
    "lng",
    "location",
}


# --- Tiny .env loader (KEY=VALUE lines) -----------------------------------------
def load_env(path: Path) -> None:
    """Populate os.environ from a simple .env file if present (does not override)."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


# --- HTTP helpers ----------------------------------------------------------------
def post_json(url: str, payload: dict[str, Any], token: str | None = None) -> Any:
    """POST JSON and return the decoded response; raises on non-2xx with the body."""
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", "replace")
        raise SystemExit(f"HTTP {err.code} from {url}\n{body}") from err


def get_json(url: str, token: str | None = None) -> Any:
    """GET JSON and return the decoded response; raises on non-2xx with the body."""
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", "replace")
        raise SystemExit(f"HTTP {err.code} from {url}\n{body}") from err


# --- Firebase Auth ---------------------------------------------------------------
def sign_in(email: str, password: str) -> dict[str, str]:
    """Sign in with email/password via the Firebase Auth REST API."""
    url = f"{IDENTITY_TOOLKIT}/accounts:signInWithPassword?key={API_KEY}"
    resp = post_json(url, {"email": email, "password": password, "returnSecureToken": True})
    print("  auth: signInWithPassword -> ok")
    print(f"    uid (localId): {resp.get('localId')}")
    print(f"    idToken expires in: {resp.get('expiresIn')}s (refresh via securetoken.googleapis.com)")
    return resp


# --- Firestore value decoding ----------------------------------------------------
def decode_value(value: dict[str, Any]) -> Any:
    """Convert a Firestore typed value into a plain Python value."""
    if "stringValue" in value:
        return value["stringValue"]
    if "integerValue" in value:
        return int(value["integerValue"])
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
        return [decode_value(v) for v in value["arrayValue"].get("values", [])]
    if "mapValue" in value:
        return {k: decode_value(v) for k, v in value["mapValue"].get("fields", {}).items()}
    return value  # unknown type; keep raw


def decode_document(doc: dict[str, Any]) -> dict[str, Any]:
    """Decode a Firestore document into {name, fields...}."""
    fields = {k: decode_value(v) for k, v in doc.get("fields", {}).items()}
    fields["__doc_id__"] = doc.get("name", "").rsplit("/", 1)[-1]
    return fields


def list_collection(collection: str, token: str, page_size: int = 25) -> list[dict[str, Any]]:
    """List documents in a Firestore collection (no ordering; robust, no index needed)."""
    url = f"{FIRESTORE}/{collection}?pageSize={page_size}"
    resp = get_json(url, token=token)
    return [decode_document(d) for d in resp.get("documents", [])]


# --- Redaction + samples ---------------------------------------------------------
def redact(obj: Any) -> Any:
    """Recursively redact secret/PII-ish fields from a decoded document."""
    if isinstance(obj, dict):
        return {k: ("<redacted>" if k in REDACT_FIELDS else redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


def save_sample(name: str, doc: dict[str, Any]) -> None:
    """Write a redacted sample document to ``docs/samples/<name>.json``."""
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    path = SAMPLES_DIR / f"{name}.json"
    path.write_text(json.dumps(redact(doc), indent=2, default=str), encoding="utf-8")
    print(f"    saved {path.relative_to(REPO_ROOT)}")


# --- Discriminator analysis ------------------------------------------------------
DISCRIMINATOR_FIELDS = [
    "category",
    "categoryId",
    "type",
    "postType",
    "role",
    "userRole",
    "isAdmin",
    "isOfficial",
    "official",
    "isStaff",
    "isVerified",
    "verified",
    "isPremium",
    "authorId",
    "author",
    "uid",
    "userId",
    "createdBy",
]


def analyze_posts(posts: list[dict[str, Any]]) -> None:
    """Print the field union and candidate discriminator values across posts."""
    if not posts:
        print("  (no posts returned — check security rules / that the account can read Post)")
        return
    field_union: set[str] = set()
    for p in posts:
        field_union.update(p.keys())
    print(f"  fields seen across {len(posts)} posts:")
    print("    " + ", ".join(sorted(field_union)))
    print("  candidate official-vs-user discriminators (distinct values):")
    for field in DISCRIMINATOR_FIELDS:
        values = {json.dumps(p[field], default=str) for p in posts if field in p}
        if values:
            shown = sorted(values)[:8]
            print(f"    {field}: {shown}")


# --- Main ------------------------------------------------------------------------
def main() -> int:
    """Run the probe: sign in, locate the Post collection, and dump samples."""
    load_env(REPO_ROOT / ".env")
    email = os.environ.get("EWEATHER_EMAIL")
    password = os.environ.get("EWEATHER_PASSWORD")
    if not email or not password:
        print(
            "Missing credentials. Set EWEATHER_EMAIL and EWEATHER_PASSWORD in .env "
            "(copy .env.example) or the environment.",
            file=sys.stderr,
        )
        return 1

    print(f"eweather probe — project {PROJECT_ID}")
    print("[1] Authenticating...")
    session = sign_in(email, password)
    token = session["idToken"]

    print("\n[2] Locating the Post collection...")
    posts: list[dict[str, Any]] = []
    found_collection = None
    for candidate in POST_COLLECTION_CANDIDATES:
        try:
            docs = list_collection(candidate, token)
        except SystemExit as err:
            print(f"    {candidate}: {err}")
            continue
        if docs:
            found_collection = candidate
            posts = docs
            print(f"    collection '{candidate}': {len(docs)} documents")
            break
        print(f"    collection '{candidate}': empty")

    if found_collection:
        print(f"\n[3] Analyzing '{found_collection}' posts...")
        analyze_posts(posts)
        # Save up to 3 samples to eyeball the official-vs-user distinction.
        for i, doc in enumerate(posts[:3]):
            save_sample(f"post_{found_collection}_{i}", doc)

    print("\n[4] Peeking at related collections (staging/alerts)...")
    for coll in OTHER_COLLECTIONS:
        try:
            docs = list_collection(coll, token, page_size=3)
        except SystemExit as err:
            print(f"    {coll}: {err}")
            continue
        print(f"    {coll}: {len(docs)} documents")
        if docs:
            save_sample(f"other_{coll}_0", docs[0])

    print("\nDone. Review docs/samples/*.json, confirm the official-vs-user field,")
    print("and record findings in docs/API_CONTRACT.md before building the client.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
