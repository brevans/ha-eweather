"""Tests for the bundled eweather Lovelace card (static path + frontend resource)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.eweather import CARD_URL
from custom_components.eweather.const import DOMAIN
from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

GET_DATA = "custom_components.eweather.api.client.EWeatherHomeAssistantApiClient.async_get_data"

EMPTY_FEED: dict[str, Any] = {
    "posts": [],
    "official": [],
    "counts": {"total": 0, "official": 0},
}


async def _setup_integration(hass: HomeAssistant) -> MockConfigEntry:
    """Set up the integration with a mocked feed, mirroring test_init."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="user@example.com",
        data={CONF_USERNAME: "user@example.com", CONF_PASSWORD: "hunter2-example"},
        unique_id="user@example.com",
    )
    entry.add_to_hass(hass)
    with patch(GET_DATA, return_value=EMPTY_FEED):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


async def test_card_served_over_http(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
) -> None:
    """The bundled card JS is served from the registered static path."""
    await _setup_integration(hass)

    client = await hass_client()
    response = await client.get(CARD_URL)
    assert response.status == 200
    body = await response.text()
    assert "eweather-feed-card" in body


async def test_card_registered_as_frontend_resource(hass: HomeAssistant) -> None:
    """Setup registers the card as an extra frontend module URL (cache-busted)."""
    await _setup_integration(hass)

    assert f"/{DOMAIN}/eweather-feed-card.js" == CARD_URL  # the URL contract cards rely on
    urls = hass.data[DATA_EXTRA_MODULE_URL].urls
    assert any(url.startswith(f"{CARD_URL}?v=") for url in urls)
