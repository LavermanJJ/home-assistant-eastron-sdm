"""Tests for the sensor platform."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from homeassistant.components.sensor import (
    ATTR_STATE_CLASS,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfEnergy,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from modbus_connection.exceptions import ModbusTimeoutError
from modbus_connection.mock import MockModbusUnit
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.eastron_sdm.sdm import MEASUREMENTS, SdmModel

from .conftest import build_unit


async def test_energy_sensors_can_drive_the_energy_dashboard(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Import and export energy must carry the attributes the dashboard needs.

    Without device_class energy, kWh and a total state class, the sensors are
    not offered as grid consumption or return -- which is most of the reason
    to run these meters at all.
    """
    for entity_id in (
        "sensor.sdm120_1_import_active_energy",
        "sensor.sdm120_1_export_active_energy",
    ):
        state = hass.states.get(entity_id)
        assert state is not None, entity_id
        assert state.attributes[ATTR_DEVICE_CLASS] == SensorDeviceClass.ENERGY
        assert state.attributes[ATTR_UNIT_OF_MEASUREMENT] == UnitOfEnergy.KILO_WATT_HOUR
        # TOTAL_INCREASING, not TOTAL: an SDM counter only climbs, and a meter
        # reset should read as a new cycle rather than as negative usage.
        assert state.attributes[ATTR_STATE_CLASS] == SensorStateClass.TOTAL_INCREASING


async def test_values_come_from_the_right_registers(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Spot-check that a value is not its neighbour's.

    The mock meter answers field n with n + 1, in declaration order.
    """
    assert hass.states.get("sensor.sdm120_1_voltage").state == "1.0"
    assert hass.states.get("sensor.sdm120_1_current").state == "2.0"
    assert hass.states.get("sensor.sdm120_1_active_power").state == "3.0"
    assert hass.states.get("sensor.sdm120_1_frequency").state == "7.0"


async def test_noisy_fields_are_registered_but_disabled(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Demand figures exist for whoever wants them, without cluttering the device."""
    registry = er.async_get(hass)
    entry = registry.async_get("sensor.sdm120_1_maximum_current_demand")
    assert entry is not None
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get("sensor.sdm120_1_maximum_current_demand") is None


async def test_diagnostics_survive_a_failed_poll(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_modbus: MockModbusUnit
) -> None:
    """A meter that stops answering must still show what it was configured as.

    Its measurements become unavailable, as they should; its node address is
    what you need to see in order to work out why.
    """
    assert hass.states.get("sensor.sdm120_1_voltage").state == "1.0"

    mock_modbus.fail_requests(ModbusTimeoutError())
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()

    assert hass.states.get("sensor.sdm120_1_voltage").state == STATE_UNAVAILABLE
    assert hass.states.get("sensor.sdm120_1_node_address").state == "1"


@pytest.mark.parametrize("model", list(SdmModel))
async def test_every_model_field_becomes_a_sensor(
    hass: HomeAssistant, model: SdmModel
) -> None:
    """No declared register may be read from the bus and then dropped.

    A field with no description would be polled every cycle and never shown,
    which is the kind of thing that only surfaces as a puzzling gap.
    """
    from custom_components.eastron_sdm.sensor import SENSORS

    described = {description.key for description in SENSORS}
    declared = set(MEASUREMENTS[model].declared_fields)
    assert declared <= described, declared - described


async def test_diagnostics_exist_even_if_the_identity_read_failed(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """The entity set must not depend on a transient bus error at startup.

    Identity is read once and is allowed to fail, so filtering the diagnostic
    entities on their value would make them appear or not appear depending on
    how busy the bus happened to be, and never come back until a reload.
    """
    unit = build_unit()
    unit.fail_read(0x0012, ModbusTimeoutError(), register_type="holding")
    unit.fail_read(0xFC00, ModbusTimeoutError(), register_type="holding")

    config_entry.add_to_hass(hass)
    with patch("custom_components.eastron_sdm.async_get_unit", return_value=unit):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    registry = er.async_get(hass)
    assert registry.async_get("sensor.sdm120_1_node_address") is not None
    assert hass.states.get("sensor.sdm120_1_node_address").state == STATE_UNKNOWN
    # Measurements are unaffected: only the identity block went missing.
    assert hass.states.get("sensor.sdm120_1_voltage").state == "1.0"
