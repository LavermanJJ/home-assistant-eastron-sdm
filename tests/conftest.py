"""Fixtures for the Eastron SDM tests."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import asynccontextmanager
import struct
from unittest.mock import patch

from homeassistant.const import CONF_DEVICE, CONF_MODEL
from homeassistant.core import HomeAssistant
from modbus_connection.mock import MockModbusConnection, MockModbusUnit
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eastron_sdm.const import (
    CONF_BAUDRATE,
    CONF_CONNECTION_TYPE,
    CONF_PARITY,
    CONF_STOPBITS,
    CONF_UNIT_ID,
    CONNECTION_SERIAL,
    DOMAIN,
)
from custom_components.eastron_sdm.sdm import MEASUREMENTS, SdmModel

SERIAL_NUMBER = 0x000123AB

SERIAL_DATA = {
    CONF_CONNECTION_TYPE: CONNECTION_SERIAL,
    CONF_DEVICE: "/dev/ttyUSB0",
    CONF_BAUDRATE: 9600,
    CONF_PARITY: "N",
    CONF_STOPBITS: 1,
    CONF_UNIT_ID: 1,
    CONF_MODEL: SdmModel.SDM120,
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> Generator[None]:
    """Make the integration under test loadable."""
    yield


def encode_float(value: float) -> list[int]:
    """Encode a float the way an SDM meter does: big-endian IEEE-754."""
    return list(struct.unpack(">HH", struct.pack(">f", value)))


def build_unit(
    model: SdmModel = SdmModel.SDM120,
    *,
    meter_code: int | None = 0x0020,
    serial_number: int | None = SERIAL_NUMBER,
) -> MockModbusUnit:
    """Return a mock meter answering every register the model declares.

    Field ``n`` reads back as ``n + 1`` so a test can tell fields apart and
    catch an address that decodes into its neighbour's value.
    """
    unit = MockModbusConnection().for_unit(1)
    for index, field in enumerate(MEASUREMENTS[model].declared_fields.values()):
        unit.input[field.address] = encode_float(float(index + 1))

    if serial_number is not None:
        unit.holding[0xFC00] = [serial_number >> 16, serial_number & 0xFFFF]
    if meter_code is not None:
        unit.holding[0xFC02] = meter_code
    unit.holding[0xFC03] = 0x0104

    unit.holding[0x0012] = encode_float(0.0)  # 8N1
    unit.holding[0x0014] = encode_float(1.0)  # node 1
    unit.holding[0x001C] = encode_float(2.0)  # 9600 baud
    return unit


@pytest.fixture
def mock_unit() -> MockModbusUnit:
    """Return a mock SDM120 on the bus."""
    return build_unit()


@pytest.fixture
def mock_modbus(mock_unit: MockModbusUnit) -> Generator[MockModbusUnit]:
    """Serve ``mock_unit`` to both setup and the config flow."""

    @asynccontextmanager
    async def _temporary(*args, **kwargs):
        yield mock_unit

    with (
        patch("custom_components.eastron_sdm.async_get_unit", return_value=mock_unit),
        patch(
            "custom_components.eastron_sdm.config_flow.async_get_temporary_unit",
            _temporary,
        ),
    ):
        yield mock_unit


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Return a configured SDM120 on a serial port."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="SDM120 (1)",
        unique_id=str(SERIAL_NUMBER),
        data=SERIAL_DATA,
    )


@pytest.fixture
async def setup_integration(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_modbus: MockModbusUnit,
) -> MockConfigEntry:
    """Set up the integration with a mock meter."""
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry
