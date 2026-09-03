"""Tests for setting up and tearing down a meter entry."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_MODEL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from modbus_connection.exceptions import ModbusTimeoutError
from modbus_connection.mock import MockModbusUnit
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eastron_sdm.const import DOMAIN
from custom_components.eastron_sdm.sdm import SdmModel

from .conftest import SERIAL_NUMBER, build_unit


async def test_setup_and_unload(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """A meter sets up, registers a device, and unloads cleanly."""
    entry = setup_integration
    assert entry.state is ConfigEntryState.LOADED

    device_registry = dr.async_get(hass)
    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, str(SERIAL_NUMBER)), entry.entry_id
    )
    assert device is not None
    assert device.manufacturer == "Eastron"
    assert device.model == "SDM120"
    assert device.serial_number == str(SERIAL_NUMBER)
    assert device.sw_version == "1.4"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_meter_not_answering_retries(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_unit: MockModbusUnit
) -> None:
    """A silent meter leaves the entry retrying rather than failed.

    The bus may simply be busy or the meter briefly unplugged; that is a
    transient condition, not a misconfiguration.
    """
    mock_unit.fail_requests(ModbusTimeoutError())
    config_entry.add_to_hass(hass)
    with patch("custom_components.eastron_sdm.async_get_unit", return_value=mock_unit):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_conflicting_line_settings_fail_the_entry(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """A port already open at another baud rate is a setup error, not a retry.

    Retrying cannot resolve it: one of the two entries has to be corrected,
    so the entry must ask for attention instead of looping.
    """
    config_entry.add_to_hass(hass)
    with patch(
        "custom_components.eastron_sdm.async_get_unit",
        side_effect=HomeAssistantError("already in use with different link settings"),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_options_change_reloads(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Changing the scan interval takes effect without a restart."""
    entry = setup_integration
    hass.config_entries.async_update_entry(entry, options={"scan_interval": 60})
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.update_interval.total_seconds() == 60


async def test_wrong_model_is_flagged_not_silently_wrong(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A mismatched model reads the wrong registers and looks plausible.

    The entry still loads -- the user may know better than the meter code --
    but the log has to say so, because every value would otherwise be quietly
    off by a few registers.
    """
    unit = build_unit(SdmModel.SDM120, meter_code=0x0070)  # reports SDM630
    config_entry.add_to_hass(hass)
    with patch("custom_components.eastron_sdm.async_get_unit", return_value=unit):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    assert "configured as SDM120 but reports meter code 0x0070" in caplog.text


async def test_incomplete_entry_data_fails_the_entry(
    hass: HomeAssistant, mock_unit: MockModbusUnit
) -> None:
    """An entry missing its connection details cannot be repaired by retrying."""
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="1", data={"connection_type": "serial"}
    )
    entry.add_to_hass(hass)
    with patch("custom_components.eastron_sdm.async_get_unit", return_value=mock_unit):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_sdm630_sets_up_with_its_own_register_map(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """The three-phase model must bring up its per-phase entities."""
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, CONF_MODEL: SdmModel.SDM630}
    )
    with patch(
        "custom_components.eastron_sdm.async_get_unit",
        return_value=build_unit(SdmModel.SDM630),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("sensor.sdm120_1_voltage_l1") is not None
    assert hass.states.get("sensor.sdm120_1_voltage_l3") is not None
    assert hass.states.get("sensor.sdm120_1_total_system_power") is not None
    # A single-phase field the SDM630 does not declare must not appear.
    assert hass.states.get("sensor.sdm120_1_voltage") is None
