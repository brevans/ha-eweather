"""
Custom integration to integrate hacs_eweather with Home Assistant.

Pulls the official eweather forecast feed (Firebase backend) into Home Assistant
as a sensor, filtering out community/user-submitted posts.

Architecture:
- Config flow setup (user, reconfigure, reauth) with email/password credentials
- DataUpdateCoordinator polling the eweather feed on an interval
- A sensor entity exposing the latest official posts

For more details about this integration, please refer to:
https://github.com/brevans/hacs-eweather

For integration development guidelines:
https://developers.home-assistant.io/docs/creating_integration_manifest
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.loader import async_get_loaded_integration

from .api import EWeatherHomeAssistantApiClient
from .const import DEFAULT_UPDATE_INTERVAL_HOURS, DOMAIN, LOGGER
from .coordinator import EWeatherHomeAssistantDataUpdateCoordinator
from .data import EWeatherHomeAssistantData

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import EWeatherHomeAssistantConfigEntry

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
]

# This integration is configured via config entries only
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EWeatherHomeAssistantConfigEntry,
) -> bool:
    """
    Set up this integration using UI.

    This is called when a config entry is loaded. It:
    1. Creates the API client with credentials from the config entry
    2. Initializes the DataUpdateCoordinator for data fetching
    3. Performs the first data refresh
    4. Sets up all platforms (sensors, switches, etc.)
    5. Registers services
    6. Sets up reload listener for config changes

    Data flow in this integration:
    1. User enters username/password in config flow (config_flow.py)
    2. Credentials stored in entry.data[CONF_USERNAME/CONF_PASSWORD]
    3. API Client initialized with credentials (api/client.py)
    4. Coordinator fetches data using authenticated client (coordinator/base.py)
    5. Entities access data via self.coordinator.data (sensor/, binary_sensor/, etc.)

    This pattern ensures credentials from setup flow are used throughout
    the integration's lifecycle for API communication.

    Args:
        hass: The Home Assistant instance.
        entry: The config entry being set up.

    Returns:
        True if setup was successful.

    For more information:
    https://developers.home-assistant.io/docs/config_entries_index/#setting-up-an-entry
    """
    # Initialize client first
    client = EWeatherHomeAssistantApiClient(
        username=entry.data[CONF_USERNAME],  # From config flow setup
        password=entry.data[CONF_PASSWORD],  # From config flow setup
        session=async_get_clientsession(hass),
    )

    # Initialize coordinator with config_entry
    update_interval_hours = float(
        entry.options.get("update_interval_hours", DEFAULT_UPDATE_INTERVAL_HOURS),
    )
    coordinator = EWeatherHomeAssistantDataUpdateCoordinator(
        hass=hass,
        logger=LOGGER,
        name=DOMAIN,
        config_entry=entry,
        update_interval=timedelta(hours=update_interval_hours),
        always_update=False,  # Only update entities when data actually changes
    )

    # Store runtime data
    entry.runtime_data = EWeatherHomeAssistantData(
        client=client,
        integration=async_get_loaded_integration(hass, entry.domain),
        coordinator=coordinator,
    )

    # https://developers.home-assistant.io/docs/integration_fetching_data#coordinated-single-api-poll-for-data-for-all-entities
    await coordinator.async_config_entry_first_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: EWeatherHomeAssistantConfigEntry,
) -> bool:
    """
    Unload a config entry.

    This is called when the integration is being removed or reloaded.
    It ensures proper cleanup of:
    - All platform entities
    - Registered services
    - Update listeners

    Args:
        hass: The Home Assistant instance.
        entry: The config entry being unloaded.

    Returns:
        True if unload was successful.

    For more information:
    https://developers.home-assistant.io/docs/config_entries_index/#unloading-entries
    """
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(
    hass: HomeAssistant,
    entry: EWeatherHomeAssistantConfigEntry,
) -> None:
    """
    Reload config entry.

    This is called when the integration configuration or options have changed.
    It unloads and then reloads the integration with the new configuration.

    Args:
        hass: The Home Assistant instance.
        entry: The config entry being reloaded.

    For more information:
    https://developers.home-assistant.io/docs/config_entries_index/#reloading-entries
    """
    await hass.config_entries.async_reload(entry.entry_id)
