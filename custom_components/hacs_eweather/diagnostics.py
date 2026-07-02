"""Diagnostics support for hacs_eweather.

Learn more about diagnostics:
https://developers.home-assistant.io/docs/core/integration_diagnostics
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import REDACTED
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.redact import async_redact_data

from .const import FIREBASE_AUTH_URL, FIRESTORE_URL

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import EWeatherHomeAssistantConfigEntry

# Fields to redact from diagnostics - CRITICAL for security!
TO_REDACT = {
    CONF_PASSWORD,
    CONF_USERNAME,
    "username",
    "password",
    "api_key",
    "token",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: EWeatherHomeAssistantConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data.coordinator
    client = entry.runtime_data.client
    integration = entry.runtime_data.integration

    # Get device and entity information
    device_reg = dr.async_get(hass)
    entity_reg = er.async_get(hass)

    # Find all devices for this integration
    devices = dr.async_entries_for_config_entry(device_reg, entry.entry_id)
    device_info = []
    for device in devices:
        entities = er.async_entries_for_device(entity_reg, device.id)
        device_info.append(
            {
                "id": device.id,
                # The device name is the entry title, i.e. the account email.
                "name": REDACTED,
                "manufacturer": device.manufacturer,
                "model": device.model,
                "sw_version": device.sw_version,
                "entity_count": len(entities),
                "entities": [
                    {
                        # entity_id is omitted: ids registered before the device was
                        # given a static name embed the slugified account email.
                        "unique_id": entity.unique_id,
                        "platform": entity.platform,
                        "original_name": entity.original_name,
                        "disabled": entity.disabled,
                        "disabled_by": entity.disabled_by.value if entity.disabled_by else None,
                    }
                    for entity in entities
                ],
            }
        )

    # Coordinator statistics
    coordinator_info = {
        "last_update_success": coordinator.last_update_success,
        "update_interval": str(coordinator.update_interval),
        "data_keys": list(coordinator.data.keys()) if isinstance(coordinator.data, dict) else None,
    }

    # API client information (no sensitive data)
    api_info = {
        "auth_endpoint": FIREBASE_AUTH_URL,
        "firestore_endpoint": FIRESTORE_URL,
        "has_credentials": bool(client._username),  # noqa: SLF001
    }

    # Integration information
    integration_info = {
        "name": integration.name,
        "version": integration.version,
        "domain": integration.domain,
        "documentation": integration.documentation,
        "issue_tracker": integration.issue_tracker,
    }

    # Config entry details (with redacted sensitive data)
    entry_info = {
        "entry_id": entry.entry_id,
        "version": entry.version,
        "minor_version": entry.minor_version,
        "domain": entry.domain,
        # The entry title and unique_id are both the account email.
        "title": REDACTED,
        "state": str(entry.state),
        "unique_id": REDACTED,
        "disabled_by": entry.disabled_by.value if entry.disabled_by else None,
        "data": async_redact_data(entry.data, TO_REDACT),
        "options": async_redact_data(entry.options, TO_REDACT),
    }

    # Error information
    error_info = {
        "last_exception": str(coordinator.last_exception) if coordinator.last_exception else None,
        "last_exception_type": (type(coordinator.last_exception).__name__ if coordinator.last_exception else None),
    }

    # Current data shape (counts only — no post content or author identifiers)
    data_sample = {}
    if isinstance(coordinator.data, dict):
        posts = coordinator.data.get("posts")
        newest = posts[0] if isinstance(posts, list) and posts and isinstance(posts[0], dict) else {}
        data_sample = {
            "counts": coordinator.data.get("counts"),
            "newest_post_created": newest.get("created"),
        }

    return {
        "entry": entry_info,
        "integration": integration_info,
        "coordinator": coordinator_info,
        "api": api_info,
        "devices": device_info,
        "data_sample": data_sample,
        "error": error_info,
    }
