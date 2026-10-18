"""Tests for eweather entry setup, unique_id migration, and unload."""

from __future__ import annotations

import copy
from typing import Any
from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eweather.const import CONF_OFFICIAL_ONLY, DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

GET_DATA = "custom_components.eweather.api.client.EWeatherHomeAssistantApiClient.async_get_data"

# Sanitized fixture posts (based on docs/samples/*.json) in the shape the client
# returns them: decoded, tagged with _official/_author, newest first.
IMAGE_ORIGINAL = (
    "https://firebasestorage.googleapis.com/v0/b/e-weather-api.appspot.com/o/"
    "post%2Forigin%2FEXAMPLE_0.jpg?alt=media&token=00000000-0000-0000-0000-000000000000"
)

OFFICIAL_POST: dict[str, Any] = {
    "__doc_id__": "EXAMPLE_OFFICIAL_POST",
    "sender": "ADMIN_UID_EXAMPLE",
    "category": "weather",
    "title": "A dangerous and prolonged heat wave begins today.",
    "text": "Stay hydrated and check on neighbors.",
    "created": "2026-07-02T12:46:10.712566Z",
    "images": [{"original": IMAGE_ORIGINAL, "isVideo": False, "ratio": 0.75}],
    "likes": 46,
    "comments": 2,
    "views": 312,
    "notification": False,
    "_official": True,
    "_author": "eweather",
}

USER_POST: dict[str, Any] = {
    "__doc_id__": "EXAMPLE_USER_POST",
    "sender": "USER_UID_EXAMPLE",
    "category": "topPhotos",
    "title": "Beautiful lake at sunset - Example Town",
    "created": "2025-06-23T15:11:07.640399Z",
    "sharePhoto": True,
    "images": [{"original": IMAGE_ORIGINAL, "isVideo": False, "ratio": 0.75}],
    "likes": 25,
    "comments": 0,
    "views": 1405,
    "notification": False,
    "_official": False,
}


def _feed_payload() -> dict[str, Any]:
    """Return a fresh copy of the client payload for one coordinator refresh."""
    official = copy.deepcopy(OFFICIAL_POST)
    user = copy.deepcopy(USER_POST)
    return {
        "posts": [official, user],
        "official": [official],
        "counts": {"total": 2, "official": 1},
    }


def _make_entry(**kwargs: Any) -> MockConfigEntry:
    defaults: dict[str, Any] = {
        "domain": DOMAIN,
        "title": "user@example.com",
        "data": {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "hunter2-example"},
        "unique_id": "user@example.com",
    }
    defaults.update(kwargs)
    return MockConfigEntry(**defaults)


async def _setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    with patch(GET_DATA, return_value=_feed_payload()):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


def _feed_entity_id(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, entry.entry_id)
    assert len(entities) == 1
    assert entities[0].unique_id == f"{entry.entry_id}_feed"
    assert entities[0].entity_id.startswith("sensor.")
    return entities[0].entity_id


async def test_setup_entry_creates_feed_sensor(hass: HomeAssistant) -> None:
    """Setup loads, and the feed sensor exposes the official post count and posts."""
    entry = _make_entry()
    await _setup_entry(hass, entry)
    assert entry.state is ConfigEntryState.LOADED

    state = hass.states.get(_feed_entity_id(hass, entry))
    assert state is not None
    # Default options: official posts only -> one official post.
    assert state.state == "1"
    assert state.attributes["official_count"] == 1
    assert state.attributes["total_count"] == 2

    posts = state.attributes["posts"]
    assert posts == [
        {
            "id": "EXAMPLE_OFFICIAL_POST",
            "title": "A dangerous and prolonged heat wave begins today.",
            "text": "Stay hydrated and check on neighbors.",
            "category": "weather",
            "created": "2026-07-02T12:46:10.712566Z",
            "author": "eweather",
            "official": True,
            "likes": 46,
            "comments": 2,
            "views": 312,
            "image": IMAGE_ORIGINAL,
            "images": [IMAGE_ORIGINAL],
        },
    ]


async def test_setup_entry_official_only_disabled_exposes_all_posts(hass: HomeAssistant) -> None:
    entry = _make_entry(options={CONF_OFFICIAL_ONLY: False})
    await _setup_entry(hass, entry)

    state = hass.states.get(_feed_entity_id(hass, entry))
    assert state is not None
    assert state.state == "2"
    posts = state.attributes["posts"]
    assert [post["id"] for post in posts] == ["EXAMPLE_OFFICIAL_POST", "EXAMPLE_USER_POST"]
    assert posts[1]["official"] is False
    assert posts[1]["author"] is None


async def test_setup_migrates_legacy_slugified_unique_id(hass: HomeAssistant) -> None:
    """A legacy slugified unique_id is rewritten to the normalized email."""
    entry = _make_entry(
        data={CONF_USERNAME: "User@Example.com", CONF_PASSWORD: "hunter2-example"},
        unique_id="user_example_com",
    )
    await _setup_entry(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    assert entry.unique_id == "user@example.com"


async def test_unload_entry(hass: HomeAssistant) -> None:
    entry = _make_entry()
    await _setup_entry(hass, entry)
    entity_id = _feed_entity_id(hass, entry)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_UNAVAILABLE
