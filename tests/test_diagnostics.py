"""Tests for the diagnostics dump."""

from __future__ import annotations

from homeassistant.const import CONF_DEVICE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from .conftest import SERIAL_NUMBER


async def test_diagnostics_redact_where_the_hardware_lives(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    setup_integration: MockConfigEntry,
) -> None:
    """A dump attached to a bug report must carry values, not identifiers."""
    result = await get_diagnostics_for_config_entry(
        hass, hass_client, setup_integration
    )

    assert result["entry"]["data"][CONF_DEVICE] == "**REDACTED**"
    assert result["info"]["serial_number"] == "**REDACTED**"
    assert str(SERIAL_NUMBER) not in str(result)

    # What the dump is for: the decoded values and whether polling worked.
    assert result["last_update_success"] is True
    assert result["values"]["voltage"] == 1.0
    assert result["info"]["model"] == "SDM120"
