"""Sensor platform for eweather."""

from __future__ import annotations

from typing import TYPE_CHECKING

from custom_components.eweather.const import PARALLEL_UPDATES as PARALLEL_UPDATES

from .feed import ENTITY_DESCRIPTION, EWeatherHomeAssistantFeedSensor

if TYPE_CHECKING:
    from custom_components.eweather.data import EWeatherHomeAssistantConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EWeatherHomeAssistantConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    async_add_entities(
        [
            EWeatherHomeAssistantFeedSensor(
                coordinator=entry.runtime_data.coordinator,
                entity_description=ENTITY_DESCRIPTION,
            ),
        ],
    )
