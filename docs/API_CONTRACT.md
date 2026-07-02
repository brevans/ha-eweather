# eweather API contract

Source of truth for the eweather → Home Assistant integration. Derived from static
analysis of the Android app (`com.saybrook.eweather_mobile`, a Flutter app) plus the
data model recovered from the compiled Dart snapshot (`libapp.so`). Fields are marked
**CONFIRMED** (directly evidenced in the APK) or **UNCONFIRMED** (inferred — must be
validated with the live probe, `tools/probe.py`).

> **Status:** Milestone 1 complete and **CONFIRMED via live probe**. The Post schema
> and the official-vs-user discriminator (Section 5) are locked. The integration client
> (`custom_components/hacs_eweather/api/client.py`) is verified end-to-end against live
> Firebase (auth, admin query, ordered fetch, filtering, and bad-credential handling).

---

## 1. Backend summary

**CONFIRMED.** The app is Flutter with a **Firebase** backend. Services in use:

| Service               | Used for                                             | Evidence                                                                                                                                                |
| --------------------- | ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Firebase Auth**     | Email/password sign-in                               | `firebase_auth` plugin, `EmailAuthProvider`, `signInWithEmailAndPassword`                                                                               |
| **Cloud Firestore**   | Posts, alerts, comments, likes, notifications, users | `cloud_firestore` plugin; collection literals `Post`, `PostStaging`, `Alert(s)`, `Comment(s)`, `Like(s)`, `Notification(s)`, `User`, `admin`, `weather` |
| **Firebase Storage**  | Post/profile images (public download URLs)           | `firebase_storage`, `getDownloadURL`, bucket `e-weather-api.appspot.com`                                                                                |
| **Realtime Database** | Secondary (likely counters/presence)                 | `firebase_database`, `DatabaseReference#set/update`, `e-weather-api-default-rtdb.firebaseio.com`                                                        |
| **Crashlytics**       | Crash reporting (not relevant to us)                 | `firebase_crashlytics_keep.xml`                                                                                                                         |

The content the integration wants — **the official forecast posts — lives in the
Firestore `Post` collection.** RTDB is not the primary content store despite its
`e-weather-api` name.

Dart source paths recovered (useful for future re-analysis):

- Model: `package:eweather_mobile/Model/Post/Post.dart`
- API/repository: `package:eweather_mobile/Controller/API/Post/Post.dart`

---

## 2. Firebase configuration

**CONFIRMED** (from `resources.arsc` + `libapp.so`). Only one API key exists in the APK.

| Key                                 | Value                                                                      |
| ----------------------------------- | -------------------------------------------------------------------------- |
| `project_id`                        | `e-weather-api`                                                            |
| `api_key` (Android)                 | `AIzaSyAWiIO_KEeAyBDhwu6wfnQ8cgM--RJhKPg`                                  |
| `app_id` (google_app_id)            | `1:807998010311:android:ef72d7aaf9434ebba89fe2`                            |
| `sender_id` / project number        | `807998010311`                                                             |
| `database_url` (RTDB)               | `https://e-weather-api-default-rtdb.firebaseio.com`                        |
| `storage_bucket`                    | `e-weather-api.appspot.com`                                                |
| `default_web_client_id` (OAuth web) | `807998010311-tm9tqaitf898r4v2cpl013eedfhla263.apps.googleusercontent.com` |

> The Android API key ships in the app and is not a secret — it identifies the Firebase
> project. Access is gated by Firebase **Security Rules** + a valid ID token, not by the
> key. The user's own credentials are what authorize reads.

---

## 3. Authentication

**CONFIRMED.** Email/password is the **only** provider wired into the app (Google/Apple/
anonymous/phone classes exist only as unused SDK scaffolding). The HA config flow collects
an email + password; the client performs the Firebase Auth REST flow below.

### 3.1 Sign in

```http
POST https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=<API_KEY>
Content-Type: application/json

{"email": "<email>", "password": "<password>", "returnSecureToken": true}
```

Response `200`:

```json
{
  "idToken": "<JWT>",
  "refreshToken": "<refresh>",
  "expiresIn": "3600",
  "localId": "<uid>",
  "email": "...",
  "registered": true
}
```

Auth errors return `{"error": {"message": "EMAIL_NOT_FOUND" | "INVALID_PASSWORD" | "USER_DISABLED" | "INVALID_LOGIN_CREDENTIALS" ...}}`
→ the client maps these to an authentication error (triggers HA reauth).

### 3.2 Refresh the ID token (expires ~3600 s)

```http
POST https://securetoken.googleapis.com/v1/token?key=<API_KEY>
Content-Type: application/x-www-form-urlencoded

grant_type=refresh_token&refresh_token=<refreshToken>
```

Response `200`: `{"id_token", "refresh_token", "expires_in", "user_id", "token_type": "Bearer"}`.

The client caches `idToken` + expiry, refreshes proactively (or on a `401`), and re-signs-in
only if the refresh token is rejected.

### 3.3 Password reset (informational; not used by the integration)

`POST /v1/accounts:sendOobCode?key=<API_KEY>` with `{"requestType": "PASSWORD_RESET", "email": "..."}`.

---

## 4. Data model

**Collections CONFIRMED** (exact casing `Post` / `User`, verified live):

| Collection              | Purpose                                     | Keep?                             |
| ----------------------- | ------------------------------------------- | --------------------------------- |
| `Post`                  | The feed — forecast posts (official + user) | **yes, filtered by author**       |
| `User`                  | User profiles; holds the `admin` flag       | **lookup — drives the filter §5** |
| `PostStaging`           | Moderation queue / drafts                   | no                                |
| `Comment(s)`, `Like(s)` | Social layer on posts                       | no                                |
| `Notification(s)`       | Push notifications                          | no                                |
| `Alerts`                | Weather alerts (empty for this account)     | maybe (future)                    |

> There is **no** `admin` collection (static analysis guessed one; it is empty). The
> admin flag lives on the `User` document — see §5.

### 4.1 Post schema (CONFIRMED via live probe)

A `Post` document (see `docs/samples/`):

| Field          | Type          | Notes                                                                    |
| -------------- | ------------- | ------------------------------------------------------------------------ |
| `sender`       | string        | **Author uid** (the discriminator input — see §5). Not `uid`/`authorId`. |
| `title`        | string        | Post headline / main text (often the full body).                         |
| `text`         | string        | Optional secondary body text.                                            |
| `category`     | string        | `weather` or `topPhotos` — **content type, not official-vs-user**.       |
| `created`      | timestamp     | ISO-8601 (e.g. `2026-07-02T12:46:10.712566Z`). Newest-first sort key.    |
| `images`       | array of maps | Each: `original`, `small` (public URLs), `isVideo`, `ratio`, `created`.  |
| `likes`        | integer       | Engagement counters.                                                     |
| `comments`     | integer       | Comment count.                                                           |
| `views`        | integer       | View count (not always present).                                         |
| `last`         | map           | Most recent comment `{created, id, text, sender}`.                       |
| `notification` | boolean       | Internal push flag.                                                      |
| `sharePhoto`   | boolean       | Present on some user photo posts.                                        |

The `weather` category is posted almost exclusively by admins (forecasts); `topPhotos` is
mostly community photos — but admins post in both, so **category is not the discriminator**.

### 4.2 Firestore REST read (CONFIRMED)

Fetch newest posts — single-field `orderBy` needs **no composite index**:

```http
POST https://firestore.googleapis.com/v1/projects/e-weather-api/databases/(default)/documents:runQuery
Authorization: Bearer <idToken>
{"structuredQuery": {"from": [{"collectionId": "Post"}],
  "orderBy": [{"field": {"fieldPath": "created"}, "direction": "DESCENDING"}],
  "limit": 150}}
```

Firestore returns typed values (`stringValue`, `integerValue`, `timestampValue`,
`mapValue`, `arrayValue`, …); the client decodes these to plain JSON.

> **Index note:** `where sender IN [...]` alone works (single-field, auto-indexed), but
> combining `IN` **with** `orderBy created` requires a composite index we can't create on
> this project. So the client fetches the newest N posts (order-by only) and filters to
> official ones client-side.

---

## 5. Official-vs-user discriminator (CONFIRMED ✅)

**A post is official iff its author's `User` document has `admin == true`.**

- The post's author is `Post.sender` (a uid).
- Look up `User/{sender}`; the boolean field **`admin`** is `true` for official accounts.
- There is **no** `admin` collection (the static-analysis guess was wrong — that collection
  is empty). The admin flag lives on the `User` doc.

Confirmed against live data — admin users returned by
`User where admin == true` (a single-field equality filter, auto-indexed):

| uid (author `sender`)                         | `User.name`           | official? |
| --------------------------------------------- | --------------------- | --------- |
| `7UhHuTPzvPU6OCVxWtr7B5b7HC22`                | `eweather`            | ✅ admin  |
| `A0naShDoTraVvHPnlgszyDjsZ342`                | `Admin  Account`      | ✅ admin  |
| (+ "Matt Cameron", "Adrian R", "drue", "kim") | —                     | ✅ admin  |
| `6ogbRDiWLCdNc9moMFrJukVBLlT2`                | `Oral Carter`         | ❌ user   |
| `V15cko3jkYUzMeLrVEcLHbVWzPf2`                | Michelle S. (sponsor) | ❌ user   |

**Client strategy (implemented in `api/client.py`):**

1. `User where admin == true` → the set of official uids + display names (cached ~6 h).
2. Fetch the newest `DEFAULT_FETCH_LIMIT` (150) posts (order-by `created`).
3. Keep posts where `sender ∈ admin uids`; attach the admin's `name` as the post author.

---

## 6. Images / media

**CONFIRMED.** Post images are **public tokenized Firebase Storage download URLs** of the
form:

```text
https://firebasestorage.googleapis.com/v0/b/e-weather-api.appspot.com/o/<path>?alt=media&token=<uuid>
```

The app renders them with `CachedNetworkImage` via a plain **unauthenticated** HTTP GET.
**Implication for HA:** image URLs stored on the post can be passed through as-is — no auth
header, no local caching/proxying needed (Milestone 4's `config/www` fallback is unnecessary
unless a URL turns out to be gated). Media-bearing fields: `imageUrl`, `images`, `photoUrl`,
`photo`, `photos`, `image`, `video`, `videos`, `urls`.

---

## 7. Open questions (only a live probe can answer)

- **Security Rules:** can any authenticated user read the whole `Post` collection, or are
  reads restricted? (Determines whether the throwaway account suffices.)
- **Exact collection casing** (`Post` vs `post`) and the **official-vs-user discriminator** (§5).
- **Full Post schema:** exact field names/types, timestamp format (`created` — Firestore
  timestamp vs epoch millis), and how the author is referenced.
- **Ordering/pagination:** is `created` present and indexed for `orderBy`, or do we sort
  client-side? Page size / cursor behavior.
- **`Alerts` / `weather` collections:** shape and whether worth surfacing later.

---

## 8. Probe plan (`tools/probe.py` — already implemented)

Standard-library only; run from the repo root with credentials in a git-ignored `.env`
(see `.env.example`). Steps:

1. Sign in via `accounts:signInWithPassword` (§3.1) → `idToken`.
2. Locate the Post collection: `GET .../documents/Post?pageSize=25` trying casing candidates.
3. Analyze: print the field union and distinct values of every candidate discriminator
   field (`category`, `uid`, `userId`, `authorId`, `isAdmin`, `role`, …).
4. Peek at `PostStaging` / `Alerts` for comparison.
5. Save up to 3 **redacted** sample documents to `docs/samples/` (tokens/emails/coords
   stripped). **Review and sanitize further before committing** — samples become test
   fixtures.

**Done when:** we can sign in and read the feed from the script, `docs/samples/` holds one
official + one user post, and §5 is filled in with the confirmed discriminator.
