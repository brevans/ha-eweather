"""Tests for the hacs_eweather config flow (user, reauth, reconfigure)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hacs_eweather.api import (
    EWeatherHomeAssistantApiClientAuthenticationError,
    EWeatherHomeAssistantApiClientCommunicationError,
)
from custom_components.hacs_eweather.const import DOMAIN
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

VALIDATE = "custom_components.hacs_eweather.config_flow_handler.config_flow.validate_credentials"
SETUP_ENTRY = "custom_components.hacs_eweather.async_setup_entry"


@pytest.fixture
def config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Return an existing configured entry (normalized email as unique_id)."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="user@example.com",
        data={CONF_USERNAME: "user@example.com", CONF_PASSWORD: "old-password"},
        unique_id="user@example.com",
    )
    entry.add_to_hass(hass)
    return entry


# -- user step ------------------------------------------------------------------------


async def test_user_flow_success(hass: HomeAssistant) -> None:
    """A successful user flow creates an entry with a normalized unique_id."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}

    with (
        patch(VALIDATE, new_callable=AsyncMock) as mock_validate,
        patch(SETUP_ENTRY, return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "User@Example.COM", CONF_PASSWORD: "hunter2-example"},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "User@Example.COM"
    assert result["data"] == {
        CONF_USERNAME: "User@Example.COM",
        CONF_PASSWORD: "hunter2-example",
    }
    assert result["result"].unique_id == "user@example.com"
    mock_validate.assert_awaited_once()


async def test_user_flow_duplicate_aborts_before_validation(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    """A duplicate account aborts before any network validation happens."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    with patch(VALIDATE, new_callable=AsyncMock) as mock_validate:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            # Different casing on purpose: unique_id is the normalized email.
            {CONF_USERNAME: "USER@Example.com", CONF_PASSWORD: "whatever"},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    mock_validate.assert_not_awaited()


@pytest.mark.parametrize(
    ("side_effect", "expected_error"),
    [
        (EWeatherHomeAssistantApiClientAuthenticationError("bad credentials"), "auth"),
        (EWeatherHomeAssistantApiClientCommunicationError("backend down"), "connection"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_user_flow_errors_then_recovery(
    hass: HomeAssistant,
    side_effect: Exception,
    expected_error: str,
) -> None:
    """Validation failures map to form errors, and the flow can still recover."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    user_input: dict[str, Any] = {
        CONF_USERNAME: "user@example.com",
        CONF_PASSWORD: "hunter2-example",
    }
    with patch(VALIDATE, new_callable=AsyncMock, side_effect=side_effect):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": expected_error}

    # The same flow completes once validation succeeds.
    with (
        patch(VALIDATE, new_callable=AsyncMock),
        patch(SETUP_ENTRY, return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input)
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY


# -- reauth ---------------------------------------------------------------------------


async def test_reauth_success_updates_password(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    result = await config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    with (
        patch(VALIDATE, new_callable=AsyncMock) as mock_validate,
        patch(SETUP_ENTRY, return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "new-password"},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_USERNAME] == "user@example.com"
    assert config_entry.data[CONF_PASSWORD] == "new-password"
    mock_validate.assert_awaited_once()


async def test_reauth_different_account_aborts(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    """Reauth must not silently swap in a different account."""
    result = await config_entry.start_reauth_flow(hass)

    with patch(VALIDATE, new_callable=AsyncMock) as mock_validate:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "other@example.com", CONF_PASSWORD: "new-password"},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    assert config_entry.data[CONF_PASSWORD] == "old-password"
    mock_validate.assert_not_awaited()


# -- reconfigure ----------------------------------------------------------------------


async def test_reconfigure_same_account_success(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    result = await config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    with (
        patch(VALIDATE, new_callable=AsyncMock) as mock_validate,
        patch(SETUP_ENTRY, return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            # Same account with different casing still counts as the same unique_id.
            {CONF_USERNAME: "USER@example.com", CONF_PASSWORD: "rotated-password"},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_USERNAME] == "USER@example.com"
    assert config_entry.data[CONF_PASSWORD] == "rotated-password"
    mock_validate.assert_awaited_once()


async def test_reconfigure_different_account_aborts(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    result = await config_entry.start_reconfigure_flow(hass)

    with patch(VALIDATE, new_callable=AsyncMock) as mock_validate:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "other@example.com", CONF_PASSWORD: "whatever"},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    assert config_entry.data[CONF_USERNAME] == "user@example.com"
    mock_validate.assert_not_awaited()
