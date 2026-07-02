# eweather → Home Assistant integration — build plan

A local, HACS-installable **custom integration** that pulls the official forecast
feed from the _eweather_ app (Southern New England, `com.saybrook.eweather_mobile`)
into Home Assistant, filtering out community/user-submitted posts.

---

## Status / start here

**Current phase:** Milestones 1–4 **done and verified**. The integration was installed
on the owner's real HA instance on **2026-07-02** and the `Forecast feed` sensor
populated (25 official posts), confirming config flow, coordinator, and sensor
end-to-end. A hardening pass (2026-07-02) fixed sign-in error classification
(transient vs credential), a config-flow session leak, unique_id normalization plus a
reauth account-mismatch guard, wired up the `enable_debugging` option, added
diagnostics redaction, and removed dead template code (`repairs.py`). The README has
been rewritten (real feature set + personal-use disclaimer) as part of this pass.

**Discovery outcome (CONFIRMED):** the app is **Flutter** but the backend is
**Firebase** (the easy case). Auth = **email/password** via Firebase Auth REST. The
forecast feed is the Firestore **`Post`** collection; images are public Storage URLs
(pass-through, no caching needed). **Official-vs-user discriminator (resolved):** a post
is official iff its author (`Post.sender` uid) has **`admin == true`** on its
`User/{uid}` document. The client caches the admin uid set (`User where admin == true`),
fetches the newest posts (order-by `created`), and keeps only admin-authored ones. A live
run returned 150 posts → 25 official (current heat-wave forecasts from "Admin Account").

> Note: the repo was scaffolded from a HA blueprint template, so the actual domain is
> **`hacs_eweather`** (not `eweather`) and it uses the template's package structure
> (`api/`, `coordinator/`, `sensor/`, …) per `AGENTS.md`, not the flat layout sketched
> below. The template's example entities have been stripped.

**Next actions, in order:**

1. Unit tests for the API client filter/parsing and the config flow (fixtures from
   `docs/samples/`).
2. Milestone 6 polish: confirm HACS + hassfest validation is green, tag a v0.1.0
   release. (Lovelace card remains deferred / out of scope.)

Keep this file updated: tick the checkboxes and move the "Current phase" line as
work lands.

---

## Goal & scope

### In scope

- Authenticate to eweather with the user's own account.
- Fetch the post feed and keep **only official eweather posts**; drop
  user-submitted content.
- Expose the result as a Home Assistant sensor with the posts in attributes.
- Config via UI (username/password), plus an options flow for settings.
- Distribute as a HACS custom repository; run entirely on the HA server.

### Out of scope (for now)

- **Lovelace card / dashboard design — deferred** until the integration is
  working and emitting data. Do not build the card yet.
- Posting/commenting or any write actions back to eweather. Read-only.
- Re-publishing eweather content anywhere outside this HA instance.

---

## Decisions locked in

| Topic             | Decision                                                                                                                                                                                    |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Distribution      | HACS **custom repository**, type _Integration_. Runs locally on HA.                                                                                                                         |
| Integration style | Full **custom integration** with config flow + options flow.                                                                                                                                |
| Discovery method  | **Static analysis of the APK** (no device available) + a **local Python probe** run by the user against the real API.                                                                       |
| Credentials       | Entered in the HA config flow, stored in HA's config entry storage (access-restricted, not encrypted). Probe script reads from a git-ignored `.env`. Never hardcoded, logged, or committed. |
| Filtering         | Keep official posts, drop user-submitted. Exact discriminator (author id vs. category vs. role flag) is **TBD from discovery**.                                                             |
| Backend etiquette | Conservative default poll interval (15–30 min), cache responses and images, send an honest `User-Agent`. Single low-frequency client.                                                       |
| Card              | Deferred (see out of scope).                                                                                                                                                                |

---

## Architecture overview

```text
reference/eweather.apk ──(static analysis)──┐
                                            ├──►  docs/API_CONTRACT.md
scripts/probe.py (user runs w/ creds) ──────┘     (base URL, auth flow,
                                                   feed endpoint, pagination,
                                                   official-vs-user field,
                                                   sample payloads)
                                                        │
                                                        ▼
                 custom_components/eweather/api.py
                 (login, token cache/refresh, fetch, filter_official, image fetch)
                                                        │
                                                        ▼
                 coordinator.py — DataUpdateCoordinator
                 (poll on interval, backoff, re-auth on 401)
                                                        │
                                                        ▼
                 sensor.eweather_feed
                 state = latest post timestamp (or count)   ← state is ≤255 chars
                 attributes = posts[] {title, ts, body, image, url, author}
                                                        │
                                                        ▼
                 [DEFERRED] Lovelace card + input_* helper controls
```

---

## Discovery strategy

We cannot intercept live traffic (no device/emulator). Two complementary paths
get us the contract anyway.

### Part A — Static analysis of the APK

Goal: identify the backend host, auth mechanism, and feed endpoints without
running the app. Put the APK at `reference/eweather.apk`, then work in
`tools/extract_api.sh`.

1. **Unzip and fingerprint the framework** — this determines difficulty:

   | Marker in APK                                                     | Framework                   | Endpoint extraction                                                                                                                                    |
   | ----------------------------------------------------------------- | --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
   | `assets/index.android.bundle`                                     | React Native                | If plain JS: grep it directly. If Hermes bytecode: `strings` on the bundle still surfaces URLs from the string table.                                  |
   | `assets/public/` + `capacitor.config.json` / `res/xml/config.xml` | Capacitor/Cordova (webview) | Easiest — it's a web app; grep the JS bundle in `assets/public/`.                                                                                      |
   | `lib/*/libapp.so` + `libflutter.so`                               | Flutter                     | Hardest. `strings libapp.so \| grep -i http` may still reveal the API host/paths. Full extraction would need runtime tooling we can't run — see risks. |
   | dex only (Kotlin/Java)                                            | Native Android              | `jadx` decompile; look for Retrofit interfaces (`@GET`/`@POST` annotations) and the base URL in the Retrofit/OkHttp builder.                           |

2. **Detect the backend type** — grep the decompiled/`strings` output for:
   - `firebaseio`, `firestore`, `googleapis`, `identitytoolkit` → **Firebase**
     (Auth + Firestore have documented REST APIs — likely the _easiest_ client).
   - `supabase` → Supabase (documented REST/gotrue auth).
   - `/wp-json/` → headless WordPress REST.
   - a custom domain with `/api`, `/v1/`, `/login`, `/feed`, `/posts` → custom REST.
     Also check `res/xml/network_security_config.xml` and `AndroidManifest.xml`
     (via `apktool`) for domain hints.

3. **Universal grep pass** across dex/`.so`/bundle:

   ```bash
   strings <artifact> | grep -iE 'https?://|/api|/v1|login|auth|token|feed|post|user'
   ```

**Deliverable:** the API base URL, the auth scheme, and candidate endpoint paths,
recorded in `docs/API_CONTRACT.md` (mark anything unconfirmed).

### Part B — Local probe against the real API

Static analysis gives endpoints; we still need real request/response bodies to
lock the JSON schema and find the official-vs-user field. Since the _user_ has
credentials and can run Python locally, we call the API directly instead of
sniffing traffic.

`scripts/probe.py`:

- Reads `EWEATHER_USER` / `EWEATHER_PASS` from env or a git-ignored `.env`.
- Performs the login discovered in Part A; captures the token/cookie handling.
- Fetches one or two feed pages.
- Saves sanitized samples to `docs/samples/` (one official post, one
  user-submitted post, side by side) and prints the auth flow.

**Deliverable:** `docs/samples/*.json` + a documented `API_CONTRACT.md` including
the exact field that distinguishes official posts (e.g. `author_id`, `role`,
`category`, `is_staff`). This is the ground truth the client and tests build on.

**Done when:** we can log in and retrieve the feed from a plain script, and we
know which posts are official.

---

## Repo structure

```text
eweather-ha/
├── plan.md                     # this file
├── README.md                   # what it is, HACS install steps, config, disclaimer
├── LICENSE
├── hacs.json                   # HACS metadata
├── .gitignore
├── .github/workflows/
│   ├── validate.yml            # HACS action + hassfest
│   └── tests.yml               # pytest
├── custom_components/eweather/
│   ├── __init__.py             # async_setup_entry / unload, coordinator wiring
│   ├── manifest.json           # domain, version, config_flow, iot_class, requirements
│   ├── const.py                # DOMAIN, defaults (interval, count)
│   ├── api.py                  # EweatherClient: login, token cache, fetch, filter, images
│   ├── coordinator.py          # EweatherCoordinator(DataUpdateCoordinator)
│   ├── config_flow.py          # username/password flow + OptionsFlow
│   ├── sensor.py               # EweatherFeedSensor
│   ├── strings.json
│   └── translations/en.json
├── scripts/
│   └── probe.py                # local discovery probe (Part B)
├── tools/
│   └── extract_api.sh          # static analysis helper (Part A)
├── docs/
│   ├── API_CONTRACT.md         # produced in Milestone 1 — source of truth
│   └── samples/                # sanitized real payloads (fixtures come from here)
├── reference/
│   └── eweather.apk            # git-ignored, provided locally
└── tests/
    ├── fixtures/               # sanitized JSON copied from docs/samples
    ├── test_api.py             # parsing + filter_official
    └── test_config_flow.py
```

### Reference: `hacs.json`

```json
{
  "name": "eweather",
  "content_in_root": false,
  "render_readme": true,
  "homeassistant": "2024.1.0"
}
```

(Set `homeassistant` to a current minimum at build time.)

### Reference: `manifest.json` (starting point — verify against current HA)

```json
{
  "domain": "eweather",
  "name": "eweather",
  "version": "0.1.0",
  "config_flow": true,
  "iot_class": "cloud_polling",
  "integration_type": "service",
  "codeowners": [],
  "dependencies": [],
  "requirements": [],
  "documentation": "https://github.com/<you>/eweather-ha",
  "issue_tracker": "https://github.com/<you>/eweather-ha/issues"
}
```

Custom integrations **must** include `version`. Add HTTP libs to `requirements`
only if not already provided by HA (HA ships `aiohttp`; prefer it over `requests`
for async).

---

## Milestones

### Milestone 0 — Scaffolding

- [x] Repo skeleton, `LICENSE`, `.gitignore` (ignore `reference/*.apk`, `.env`, `__pycache__/`, `.venv/`).
- [x] `hacs.json`, minimal `manifest.json`, placeholder `__init__.py` + `const.py`.
- [x] README stub with the install-via-custom-repo steps and a personal-use disclaimer
      (README fully rewritten 2026-07-02 with the real feature set + disclaimer).
- [x] CI: HACS validate + hassfest.
- **Done:** repo can be added to HACS as a custom Integration and loads without error (no entities yet).

### Milestone 1 — API discovery

- [x] `tools/extract_api.sh`: unzip, fingerprint, grep (Part A) (superseded: findings captured directly in API_CONTRACT.md; helper script not kept).
- [x] `scripts/probe.py`: login + feed capture (Part B) (lives at `tools/probe.py`).
- [x] `docs/API_CONTRACT.md`: base URL, auth flow + token lifetime, feed endpoint(s), pagination, **official-vs-user field**.
- [x] `docs/samples/`: one official + one user post, sanitized.
- **Done:** we can authenticate and fetch the feed from a script, and we know how to identify official posts.

### Milestone 2 — API client (`api.py`)

- [x] `EweatherClient.login()` with token/cookie caching + expiry.
- [x] `fetch_feed()` with pagination and error handling (raise typed errors for auth vs. transient).
- [x] `filter_official()` per the discovery field; configurable.
- [x] Optional `fetch_image()` returning bytes (for later caching) (not needed — image URLs are public pass-through).
- [ ] Unit tests against `tests/fixtures/`.
- **Done:** client returns a clean list of official post objects from recorded fixtures and live.

### Milestone 3 — Integration core

- [x] `config_flow.py`: collect + validate username/password (test login during the flow).
- [x] `coordinator.py`: `DataUpdateCoordinator` polling at the configured interval, backoff, **re-auth on 401**.
- [x] `__init__.py`: `async_setup_entry` / `async_unload_entry`, store coordinator.
- [x] Finalized `manifest.json`.
- **Done:** integration sets up from the UI with credentials; the entry loads and the coordinator fetches without error.

### Milestone 4 — Sensor entity

- [x] `sensor.py`: `sensor.eweather_feed`; **state = latest post timestamp or count** (≤255 chars); **attributes = posts[]** (title, timestamp, body, image, url, author).
- [x] Image handling: if image URLs are auth-gated, cache to `config/www/eweather/…` and expose `/local/eweather/…`; otherwise pass URLs through (image URLs are public — passed through as-is, no caching needed).
- **Done:** posts visible in Developer Tools → States with correct filtering.

### Milestone 5 — Options flow

- [x] Options: post count, category/filter selection, poll interval, show/cache photos
      (interval + official-only filter + post count shipped; `enable_debugging` now
      functional as of 2026-07-02; show/cache photos dropped — images are public
      pass-through).
- [x] Coordinator + sensor respect options; changes apply without a restart.
- **Done:** settings adjustable in the UI and honored.

### Milestone 6 — Polish & release

- [x] README: install, configure, troubleshoot; disclaimer about ToS / personal use.
- [ ] Passing HACS + hassfest validation; tag a release.
- **Done:** clean install from scratch via HACS on a real HA instance.

_(Card + dashboard work is a separate effort after Milestone 6.)_

---

## Credential & security rules

- Credentials are entered in the **config flow** and live in HA's config entry
  storage (access-restricted, not encrypted at rest). Never write them to YAML.
- `scripts/probe.py` reads creds from a **git-ignored `.env`**. Never hardcode.
- Never log credentials or tokens. Redact before writing anything to `docs/`.
- **Do not commit the APK** (`reference/*.apk` is git-ignored) — size and
  redistribution concerns.
- Fixtures in `tests/` must be sanitized (no real tokens, no PII from other users).
- Cache the auth token to HA storage with its expiry; refresh on 401 rather than
  logging in every poll.

---

## Testing strategy

- **Unit:** `api.py` parsing and `filter_official()` against sanitized fixtures
  in `tests/fixtures/` (sourced from `docs/samples/`). This is the highest-value
  coverage — the filter is the core requirement.
- **Config flow:** use `pytest-homeassistant-custom-component`; mock the client
  to test success, bad-credentials, and cannot-connect paths.
- **Coordinator:** test the re-auth-on-401 path and backoff with a mocked client.
- Keep tests offline; no live calls in CI.

---

## Risks & open questions

- **Framework unknown → discovery difficulty unknown.** If it's Flutter, static
  endpoint extraction may only yield the host. Mitigations: `strings` on
  `libapp.so`; probe common REST paths; if truly blocked, revisit borrowing a
  device for a one-time capture. Resolve early in Milestone 1.
- **Backend type unknown.** Firebase/Supabase would actually _simplify_ the
  client (documented auth + data REST APIs). Confirm in Milestone 1.
- **Image auth-gating unknown.** May force local caching (handled in Milestone 4).
- **Token lifetime/refresh unknown.** Coordinator must handle re-auth cleanly.
- **API stability.** Small indie app; endpoints may change without notice. Keep
  `api.py` thin and the contract documented so fixes are localized.
- **Terms of service.** Automating access may conflict with the app's terms
  (see eweatherapp.com/terms). This is a personal, read-only, low-frequency,
  single-user integration; content stays on the user's own HA instance.

---

## References

- Package: `com.saybrook.eweather_mobile`
- Play Store: <https://play.google.com/store/apps/details?id=com.saybrook.eweather_mobile>
- App Store: <https://apps.apple.com/us/app/eweather-app/id1566403306>
- Website (WordPress marketing only): <https://eweatherapp.com>
- Official posts also mirrored to Facebook: <https://www.facebook.com/eweather13/>
- HA — Integration development: <https://developers.home-assistant.io/docs/creating_component_index>
- HA — Config flow: <https://developers.home-assistant.io/docs/config_entries_config_flow_handler>
- HA — DataUpdateCoordinator: <https://developers.home-assistant.io/docs/integration_fetching_data>
- HACS — Publishing/custom repositories: <https://hacs.xyz/docs/publish/start>
- Tools: `jadx`, `apktool`, and (fallback, needs a device) `HTTP Toolkit` / `mitmproxy` / `apk-mitm`

---

## Working with Claude Code

- Treat `docs/API_CONTRACT.md` as the **source of truth**; regenerate the client
  and fixtures from it when it changes.
- Start at Milestone 0 and go in order — later milestones depend on the contract.
- Update the [Status](#status--start-here) line and check boxes as work lands.
- Prefer `aiohttp` (async, ships with HA) over `requests` in the integration.
- Keep the APK at `reference/eweather.apk`; it is git-ignored by design.
