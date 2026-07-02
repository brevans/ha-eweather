# EWeather Home Assistant Integration

[![GitHub Release][releases-shield]][releases]
[![License][license-shield]](LICENSE)
[![HACS Custom][hacsbadge]][hacs]
![Project Maintenance][maintenance-shield]

A personal, read-only [Home Assistant](https://www.home-assistant.io/) integration for the **eweather** app (Southern New England weather, `com.saybrook.eweather_mobile`). It signs in with your own eweather account, pulls the newest posts from the app's feed, filters them to **official posts only** (posts authored by admin accounts), and exposes them as a sensor you can use in dashboards and automations.

> [!IMPORTANT]
> **Personal-use disclaimer.** This is an unofficial project, not affiliated with or endorsed by eweather. It is read-only, uses a single account, and polls at a low frequency. Feed content stays on your own Home Assistant instance — do not re-publish it anywhere. Use it in a manner consistent with eweather's terms of service ([eweatherapp.com](https://eweatherapp.com)).

## What you get

One sensor: **Forecast feed**. Its state is the number of posts exposed, and the post content lives in its attributes:

| Attribute        | Description                                                   |
| ---------------- | ------------------------------------------------------------- |
| `posts`          | List of the newest posts (fields below)                       |
| `official_count` | Number of official (admin-authored) posts in the latest fetch |
| `total_count`    | Total number of posts fetched before filtering                |

Each entry in `posts` has: `id`, `title`, `text`, `category`, `created`, `author`, `official`, `likes`, `comments`, `views`, `image`, `images`.

Post images are public URLs, so they can be used directly in cards — and the integration ships its own dashboard card (below).

The integration registers no services and installs no extra Python packages. Requires Home Assistant **2026.4.0** or newer.

## Installation

### Option 1: HACS custom repository (recommended)

1. In Home Assistant, open **HACS** → **Integrations**
2. Click the **⋮** menu (top right) → **Custom repositories**
3. Add `https://github.com/brevans/hacs-eweather` with type **Integration**
4. Find "EWeather Home Assistant Integration" in HACS and click **Download**
5. **Restart Home Assistant**

### Option 2: Manual

1. Copy the `custom_components/hacs_eweather/` folder from this repository into your Home Assistant `config/custom_components/` directory
2. **Restart Home Assistant**

## Configuration

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for **"EWeather"**
3. Enter your eweather account **email** and **password** (sign-in is verified during setup)

Credentials are stored in Home Assistant's config entry storage (plain JSON in the `.storage` directory, protected by filesystem permissions — not encrypted at rest). If they stop working, Home Assistant will prompt you to reauthenticate.

### Options

After setup, click **Configure** on the integration to adjust:

| Option                  | Default | Description                                              |
| ----------------------- | ------- | -------------------------------------------------------- |
| `update_interval_hours` | 1       | How often to poll the feed (0.25–24 hours)               |
| `official_only`         | on      | Only expose posts authored by official (admin) accounts  |
| `post_count`            | 10      | How many posts to expose in the sensor attributes (1–50) |
| `enable_debugging`      | off     | Sets this integration's logger to debug level            |

Option changes apply without a restart.

## Dashboard card

The integration bundles a Lovelace card, **EWeather Feed Card**, and registers it automatically — no manual resource configuration needed. It shows the most recent post with its author, category, and timestamp (relative and absolute), and a swipeable carousel for the post's photos (arrows, dots, and touch swipe; tap a photo to open the original). Optional ‹ › paging in the header steps through the older posts in the sensor's attributes.

Add it from the dashboard card picker (search "EWeather"), or in YAML:

```yaml
type: custom:eweather-feed-card
entity: sensor.eweather_forecast_feed # check your entity id in Developer Tools → States
title: eweather
```

| Option          | Default    | Description                               |
| --------------- | ---------- | ----------------------------------------- |
| `entity`        | (required) | The Forecast feed sensor                  |
| `title`         | `eweather` | Card header title (empty string hides it) |
| `show_post_nav` | `true`     | Show ‹ › paging through older posts       |
| `image_height`  | `300`      | Height of the photo carousel in pixels    |

After upgrading the integration, restart Home Assistant and hard-refresh the browser (the card is versioned, so caches bust automatically on release upgrades).

## Integration icon

Brand assets recreated from the official app artwork live in [`assets/brands/hacs_eweather/`](assets/brands/hacs_eweather/). Home Assistant only displays integration icons served from [home-assistant/brands](https://github.com/home-assistant/brands), so the icon appears in the UI once those files are submitted there (as `custom_integrations/hacs_eweather/`) and the PR is merged.

## Troubleshooting

- **Debug logging:** turn on the `enable_debugging` option, or add this to `configuration.yaml`:

  ```yaml
  logger:
    logs:
      custom_components.hacs_eweather: debug
  ```

- **"We found a custom integration ... not tested by Home Assistant"** in the startup log is normal for any custom integration, including this one.
- **"Email or password is incorrect"** during setup usually means exactly that — but it can also mean the account genuinely cannot sign in via Firebase email/password. Verify you can sign in with the same email and password in the eweather app itself.

## Development

This repository is devcontainer-based (VS Code Dev Containers or GitHub Codespaces):

- `script/setup` — install dependencies
- `script/develop` — run a local Home Assistant at <http://localhost:8123>
- `script/check` — type-check + lint + spell
- `script/test` — run tests

The API contract (Firebase Auth + Firestore, post schema, official-post discriminator) is documented in [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md). A discovery probe lives at `tools/probe.py` and reads credentials from a git-ignored `.env` (see `.env.example`).

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

[hacs]: https://github.com/hacs/integration
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
[license-shield]: https://img.shields.io/github/license/brevans/hacs-eweather.svg?style=for-the-badge
[maintenance-shield]: https://img.shields.io/badge/maintainer-%40brevans-blue.svg?style=for-the-badge
[releases-shield]: https://img.shields.io/github/release/brevans/hacs-eweather.svg?style=for-the-badge
[releases]: https://github.com/brevans/hacs-eweather/releases
