"""
Core DataUpdateCoordinator implementation for eweather.

This module contains the main coordinator class that manages data fetching
and updates for all entities in the integration. It handles refresh cycles,
error handling, and triggers reauthentication when needed.

For more information on coordinators:
https://developers.home-assistant.io/docs/integration_fetching_data#coordinated-single-api-poll-for-data-for-all-entities
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from custom_components.eweather.api import (
    EWeatherHomeAssistantApiClientAuthenticationError,
    EWeatherHomeAssistantApiClientError,
)
from custom_components.eweather.const import LOGGER
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

if TYPE_CHECKING:
    from custom_components.eweather.data import EWeatherHomeAssistantConfigEntry


class EWeatherHomeAssistantDataUpdateCoordinator(DataUpdateCoordinator):
    """
    Class to manage fetching data from the API.

    This coordinator handles all data fetching for the integration and distributes
    updates to all entities. It manages:
    - Periodic data updates based on update_interval
    - Error handling and recovery
    - Authentication failure detection and reauthentication triggers
    - Data distribution to all entities
    - Context-based data fetching (only fetch data for active entities)

    For more information:
    https://developers.home-assistant.io/docs/integration_fetching_data#coordinated-single-api-poll-for-data-for-all-entities

    Attributes:
        config_entry: The config entry for this integration instance.
    """

    config_entry: EWeatherHomeAssistantConfigEntry

    async def _async_setup(self) -> None:
        """Set up the coordinator (runs once before the first refresh)."""
        LOGGER.debug("Coordinator setup complete for %s", self.config_entry.entry_id)

    async def _async_update_data(self) -> Any:
        """
        Fetch the eweather feed via the API client.

        Called automatically on the configured update_interval. Returns the client's
        payload: ``{"posts": [...], "official": [...], "counts": {...}}``.

        Raises:
            ConfigEntryAuthFailed: If the credentials are rejected, triggering reauth.
            UpdateFailed: If data fetching fails for other reasons (HA retries with
                backoff and logs the failure itself).
        """
        try:
            return await self.config_entry.runtime_data.client.async_get_data()
        except EWeatherHomeAssistantApiClientAuthenticationError as exception:
            LOGGER.warning("Authentication error - %s", exception)
            raise ConfigEntryAuthFailed(
                translation_domain="eweather",
                translation_key="authentication_failed",
            ) from exception
        except EWeatherHomeAssistantApiClientError as exception:
            # DataUpdateCoordinator logs UpdateFailed itself; avoid duplicate tracebacks.
            raise UpdateFailed(
                translation_domain="eweather",
                translation_key="update_failed",
            ) from exception
