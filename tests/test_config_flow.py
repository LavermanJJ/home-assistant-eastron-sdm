"""Tests for the config flow."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.const import (
    CONF_DEVICE,
    CONF_HOST,
    CONF_MODEL,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from modbus_connection.exceptions import (
    IllegalDataAddressError,
    ModbusDesyncError,
    ModbusTimeoutError,
)
from modbus_connection.mock import MockModbusUnit
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eastron_sdm.config_flow import SdmConfigFlow
from custom_components.eastron_sdm.const import (
    CONF_BAUDRATE,
    CONF_CONNECTION_TYPE,
    CONF_FRAMER,
    CONF_PARITY,
    CONF_STOPBITS,
    CONF_UNIT_ID,
    CONNECTION_SERIAL,
    CONNECTION_TCP,
    DOMAIN,
)
from custom_components.eastron_sdm.sdm import SdmModel

from .conftest import SERIAL_DATA, SERIAL_NUMBER, build_unit

SERIAL_INPUT = {
    CONF_DEVICE: "/dev/ttyUSB0",
    CONF_BAUDRATE: "9600",
    CONF_PARITY: "N",
    CONF_STOPBITS: "1",
    CONF_UNIT_ID: 1,
}

TCP_INPUT = {
    CONF_HOST: "192.168.1.50",
    CONF_PORT: 502,
    CONF_FRAMER: "rtu",
    CONF_UNIT_ID: 2,
}


@contextmanager
def serving(
    unit: MockModbusUnit | None = None, *, error: Exception | None = None
) -> Iterator[None]:
    """Patch the bus for both the flow and the setup that follows it.

    A successful flow creates an entry, and creating an entry sets it up
    immediately -- so a test that only patched the flow would let setup reach
    for a real port or socket.
    """

    @asynccontextmanager
    async def _temporary(*args, **kwargs):
        if error is not None:
            raise error
        yield unit

    with (
        patch(
            "custom_components.eastron_sdm.config_flow.async_get_temporary_unit",
            _temporary,
        ),
        patch(
            "custom_components.eastron_sdm.async_get_unit",
            return_value=unit or build_unit(),
        ),
        patch("serial.tools.list_ports.comports", return_value=[]),
    ):
        yield


async def _start_serial(hass: HomeAssistant) -> str:
    """Open the flow and pick the serial branch."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": CONNECTION_SERIAL}
    )
    assert result["step_id"] == CONNECTION_SERIAL
    return result["flow_id"]


async def test_serial_meter_is_identified_and_created(hass: HomeAssistant) -> None:
    """A meter reporting a known code is set up without asking for the model."""
    flow_id = await _start_serial(hass)
    with serving(build_unit(SdmModel.SDM120, meter_code=0x0020)):
        result = await hass.config_entries.flow.async_configure(flow_id, SERIAL_INPUT)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "SDM120 (1)"
    assert result["result"].unique_id == str(SERIAL_NUMBER)
    assert result["data"] == {
        CONF_CONNECTION_TYPE: CONNECTION_SERIAL,
        CONF_DEVICE: "/dev/ttyUSB0",
        CONF_BAUDRATE: 9600,
        CONF_PARITY: "N",
        CONF_STOPBITS: 1,
        CONF_UNIT_ID: 1,
        CONF_MODEL: SdmModel.SDM120,
    }


async def test_form_values_are_stored_as_numbers(hass: HomeAssistant) -> None:
    """Baud rate and stop bits must not reach the entry as strings.

    Connection parameters are compared by value to decide who shares a
    connection, so a string 9600 and an int 9600 would open two ports.
    """
    flow_id = await _start_serial(hass)
    with serving(build_unit()):
        result = await hass.config_entries.flow.async_configure(flow_id, SERIAL_INPUT)

    data = result["data"]
    assert isinstance(data[CONF_BAUDRATE], int)
    assert isinstance(data[CONF_STOPBITS], int)
    assert isinstance(data[CONF_UNIT_ID], int)


async def test_unknown_meter_code_asks_for_the_model(hass: HomeAssistant) -> None:
    """An unrecognised meter code leads to the model step, not to a failure."""
    flow_id = await _start_serial(hass)
    with serving(build_unit(meter_code=0x00FF)):
        result = await hass.config_entries.flow.async_configure(flow_id, SERIAL_INPUT)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "model_unknown_code"
    assert result["description_placeholders"] == {"meter_code": "0x00FF"}

    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_MODEL: SdmModel.SDM630}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_MODEL] == SdmModel.SDM630


async def test_meter_without_device_info_block_still_sets_up(
    hass: HomeAssistant,
) -> None:
    """A meter that refuses 0xFC00 but answers the bus is not a dead meter."""
    unit = build_unit(SdmModel.SDM630)
    unit.fail_read(0xFC00, IllegalDataAddressError(), register_type="holding")

    flow_id = await _start_serial(hass)
    with serving(unit):
        result = await hass.config_entries.flow.async_configure(flow_id, SERIAL_INPUT)

    assert result["step_id"] == "model"
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_MODEL: SdmModel.SDM630}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    # No serial number to key on, so the bus position identifies it instead.
    assert result["result"].unique_id == "serial-/dev/ttyUSB0-1"


async def test_silent_meter_shows_cannot_connect_and_recovers(
    hass: HomeAssistant,
) -> None:
    """A wrong unit ID or baud rate is correctable without restarting the flow."""
    unit = build_unit()
    unit.fail_requests(ModbusTimeoutError())

    flow_id = await _start_serial(hass)
    with serving(unit):
        result = await hass.config_entries.flow.async_configure(flow_id, SERIAL_INPUT)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    with serving(build_unit()):
        result = await hass.config_entries.flow.async_configure(flow_id, SERIAL_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_conflicting_line_settings_are_explained(hass: HomeAssistant) -> None:
    """Two baud rates on one port is a wiring truth the form has to state."""
    flow_id = await _start_serial(hass)
    with serving(error=HomeAssistantError("already in use with different settings")):
        result = await hass.config_entries.flow.async_configure(flow_id, SERIAL_INPUT)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "bus_settings_conflict"}


async def test_the_same_meter_twice_aborts(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """A meter is identified by serial number, wherever it is on the bus."""
    config_entry.add_to_hass(hass)

    flow_id = await _start_serial(hass)
    with serving(build_unit()):
        result = await hass.config_entries.flow.async_configure(
            flow_id, {**SERIAL_INPUT, CONF_UNIT_ID: 7}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_second_meter_on_the_bus_is_prefilled(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Adding meters 2 to 6 should only require a new unit ID."""
    config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    with serving():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": CONNECTION_SERIAL}
        )

    suggested = {
        key.schema: key.description["suggested_value"]
        for key in result["data_schema"].schema
        if key.description and "suggested_value" in key.description
    }
    assert suggested[CONF_DEVICE] == SERIAL_DATA[CONF_DEVICE]
    assert suggested[CONF_PARITY] == SERIAL_DATA[CONF_PARITY]
    # Stringified to match the dropdown's option values, which are strings; an
    # int would match no option and the field would render unset.
    assert suggested[CONF_BAUDRATE] == str(SERIAL_DATA[CONF_BAUDRATE])
    assert suggested[CONF_STOPBITS] == str(SERIAL_DATA[CONF_STOPBITS])
    # The one field that must differ between meters is not carried over.
    assert CONF_UNIT_ID not in suggested


async def test_tcp_gateway(hass: HomeAssistant) -> None:
    """A serial gateway is reached over TCP with RTU framing."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": CONNECTION_TCP}
    )
    with serving(build_unit()):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], TCP_INPUT
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_CONNECTION_TYPE] == CONNECTION_TCP
    assert result["data"][CONF_FRAMER] == "rtu"
    assert result["data"][CONF_PORT] == 502


async def test_reconfigure_keeps_the_entry(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Moving a meter to a new unit ID updates the entry in place."""
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reconfigure_flow(hass)

    with serving(build_unit()):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**SERIAL_INPUT, CONF_UNIT_ID: 4}
        )

        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_UNIT_ID] == 4
    # The form carries only link settings; everything else has to survive, or
    # the entry cannot be set up again.
    assert config_entry.data[CONF_MODEL] == SdmModel.SDM120
    assert config_entry.state is ConfigEntryState.LOADED
    # The title names the meter's place on the bus, so moving it renames it.
    assert config_entry.title == "SDM120 (4)"

    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()


async def test_reconfigure_rejects_a_different_meter(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Pointing an entry at another meter would silently rename its history."""
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reconfigure_flow(hass)

    with serving(build_unit(serial_number=0x00FFFFFF)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], SERIAL_INPUT
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "different_meter"


async def test_options_flow_sets_the_scan_interval(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """The polling rate is adjustable without removing the meter."""
    config_entry.add_to_hass(hass)
    with serving(build_unit()):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.options.async_init(config_entry.entry_id)
        assert result["step_id"] == "init"
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_SCAN_INTERVAL: 120}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options[CONF_SCAN_INTERVAL] == 120
    assert config_entry.runtime_data.update_interval.total_seconds() == 120


async def test_ports_are_offered_when_pyserial_can_list_them(
    hass: HomeAssistant,
) -> None:
    """The converter should be pickable rather than typed from memory."""
    port = SimpleNamespace(device="/dev/ttyUSB0", description="FT232R USB UART")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    with patch("serial.tools.list_ports.comports", return_value=[port]):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": CONNECTION_SERIAL}
        )

    selector = next(
        value
        for key, value in result["data_schema"].schema.items()
        if key.schema == CONF_DEVICE
    )
    assert selector.config["options"] == [
        {"value": "/dev/ttyUSB0", "label": "/dev/ttyUSB0 (FT232R USB UART)"}
    ]
    assert selector.config["custom_value"] is True


async def test_setup_still_possible_without_pyserial(hass: HomeAssistant) -> None:
    """Pyserial is not guaranteed present; typing the path must still work.

    Home Assistant core does not require it, and the shared connection manager
    drives serial ports through tmodbus, which uses serialx instead.
    """
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    with patch.dict("sys.modules", {"serial.tools": None}):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": CONNECTION_SERIAL}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == CONNECTION_SERIAL


async def test_reconfigure_meter_without_serial_number(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """A meter with no serial number must still be movable on the bus.

    Its unique ID is derived from where it sits, which is the very thing a
    reconfigure changes -- so comparing IDs would read every move as a swap
    for a different meter.
    """
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, unique_id="serial-/dev/ttyUSB0-1"
    )
    unit = build_unit(SdmModel.SDM630)
    unit.fail_read(0xFC00, IllegalDataAddressError(), register_type="holding")

    result = await config_entry.start_reconfigure_flow(hass)
    with serving(unit):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**SERIAL_INPUT, CONF_UNIT_ID: 4}
        )
        await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_UNIT_ID] == 4

    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()


async def test_select_defaults_match_option_type(hass: HomeAssistant) -> None:
    """Dropdown defaults must be the same type as the dropdown's options.

    The selector validates against string options, so an int default matches
    nothing: the field renders unset, and voluptuous raises if the key is ever
    filled from the default rather than from the form.
    """
    flow_id = await _start_serial(hass)
    with serving():
        result = await hass.config_entries.flow.async_configure(flow_id, None)

    for key in result["data_schema"].schema:
        if key.schema in (CONF_BAUDRATE, CONF_STOPBITS):
            assert isinstance(key.default(), str), (
                f"{key.schema} default is {key.default()!r}, "
                "but the selector's options are strings"
            )


async def test_reconfigure_can_change_line_settings(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Changing a baud rate must not be blocked by the entry's own connection.

    The shared connection manager refuses a second set of line settings on one
    endpoint, and the entry being reconfigured is still holding that endpoint
    with the old ones. The stand-in below enforces exactly that rule, so this
    fails unless the flow lets go of its own connection before probing.
    """
    config_entry.add_to_hass(hass)
    with serving(build_unit()):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED

    @asynccontextmanager
    async def _one_set_of_line_settings_per_port(hass_, params, unit_id):
        if config_entry.state is ConfigEntryState.LOADED:
            raise HomeAssistantError(
                f"Modbus device {params.endpoint} is already in use with "
                "different link settings"
            )
        yield build_unit()

    result = await config_entry.start_reconfigure_flow(hass)
    with (
        patch(
            "custom_components.eastron_sdm.config_flow.async_get_temporary_unit",
            _one_set_of_line_settings_per_port,
        ),
        patch(
            "custom_components.eastron_sdm.async_get_unit", return_value=build_unit()
        ),
        patch("serial.tools.list_ports.comports", return_value=[]),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**SERIAL_INPUT, CONF_BAUDRATE: "19200"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_BAUDRATE] == 19200

    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()


async def test_failed_reconfigure_puts_the_entry_back(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Abandoning a reconfigure must not leave the meter unloaded.

    The flow unloads the entry to free the port before probing, so a probe
    that fails has to restore it rather than leave the user's meter dark.
    """
    config_entry.add_to_hass(hass)
    with serving(build_unit()):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    silent = build_unit()
    silent.fail_requests(ModbusTimeoutError())

    @asynccontextmanager
    async def _no_answer(*args, **kwargs):
        yield silent

    result = await config_entry.start_reconfigure_flow(hass)
    with (
        patch(
            "custom_components.eastron_sdm.config_flow.async_get_temporary_unit",
            _no_answer,
        ),
        # The entry's old settings still work; it is the settings being probed
        # that do not, so the restoring reload has to find a live meter.
        patch(
            "custom_components.eastron_sdm.async_get_unit", return_value=build_unit()
        ),
        patch("serial.tools.list_ports.comports", return_value=[]),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], SERIAL_INPUT
        )
        await hass.async_block_till_done()

    assert result["errors"] == {"base": "cannot_connect"}
    assert config_entry.state is ConfigEntryState.LOADED

    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()


async def test_a_failed_probe_keeps_what_was_typed(hass: HomeAssistant) -> None:
    """A wrong baud rate must not also cost the user the port they typed."""
    unit = build_unit()
    unit.fail_requests(ModbusTimeoutError())

    flow_id = await _start_serial(hass)
    with serving(unit):
        result = await hass.config_entries.flow.async_configure(
            flow_id,
            {**SERIAL_INPUT, CONF_DEVICE: "/dev/ttyUSB7", CONF_BAUDRATE: "2400"},
        )

    suggested = {
        key.schema: key.description["suggested_value"]
        for key in result["data_schema"].schema
        if key.description and "suggested_value" in key.description
    }
    assert suggested[CONF_DEVICE] == "/dev/ttyUSB7"
    assert suggested[CONF_BAUDRATE] == "2400"


async def test_meter_with_no_code_is_not_described_as_a_fault(
    hass: HomeAssistant,
) -> None:
    """The SDM120CT and SDM230 document no meter code, so this is the norm.

    Telling those users their meter "reported model code none, which this
    integration does not recognise" would describe correct hardware as broken.
    """
    flow_id = await _start_serial(hass)
    # The register is absent, so the meter answers it with zero -- which is
    # not a code, and must not be quoted back as an unrecognised one.
    with serving(build_unit(meter_code=None)):
        result = await hass.config_entries.flow.async_configure(flow_id, SERIAL_INPUT)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "model"
    assert result["description_placeholders"] == {}

    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_MODEL: SdmModel.SDM230}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_MODEL] == SdmModel.SDM230


async def test_reconfigure_returns_to_the_tcp_form(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """A TCP entry must reopen as TCP, not as the serial form it never used."""
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry,
        data={
            CONF_CONNECTION_TYPE: CONNECTION_TCP,
            CONF_MODEL: SdmModel.SDM120,
            **TCP_INPUT,
        },
    )

    result = await config_entry.start_reconfigure_flow(hass)
    assert result["step_id"] == CONNECTION_TCP

    with serving(build_unit()):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**TCP_INPUT, CONF_PORT: 5020}
        )
        await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_PORT] == 5020
    assert config_entry.data[CONF_CONNECTION_TYPE] == CONNECTION_TCP

    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()


async def test_a_garbled_frame_is_reported_as_cannot_connect(
    hass: HomeAssistant,
) -> None:
    """A desynced RS485 line is a bus fault, not a Home Assistant crash.

    Noise, a missing termination resistor or a second master talking over the
    conversation all surface as a frame that does not parse -- which is
    neither a timeout nor a refusal, and so falls to the catch-all arm.
    """
    unit = build_unit()
    unit.fail_requests(ModbusDesyncError("frame out of step"))

    flow_id = await _start_serial(hass)
    with serving(unit):
        result = await hass.config_entries.flow.async_configure(flow_id, SERIAL_INPUT)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_data_that_cannot_describe_a_link_is_refused(
    hass: HomeAssistant,
) -> None:
    """The probe must not be reached with parameters that cannot be built.

    Nothing the forms accept can get here today -- every field `build_params`
    reads is required by the schema -- so this drives the guard directly. It
    is what keeps a future selector or model from turning a malformed entry
    into a traceback on the way to the bus.
    """
    flow = SdmConfigFlow()
    flow.hass = hass

    assert await flow._async_try({CONF_CONNECTION_TYPE: CONNECTION_TCP}) == {
        "base": "invalid_link"
    }


async def test_reconfigure_offers_the_model_the_meter_reports(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """A meter contradicting its entry is the one case worth preselecting.

    The entry says SDM120 and the meter says SDM630. Those have different
    register maps, so one of the two is reading the wrong addresses -- and a
    wrong address decodes to a plausible number rather than to an error.
    """
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reconfigure_flow(hass)

    with serving(build_unit(SdmModel.SDM120, meter_code=0x0070)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], SERIAL_INPUT
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "model_mismatch"
    assert result["description_placeholders"] == {
        "meter_code": "0x0070",
        "detected": "SDM630",
        "configured": "SDM120",
    }
    suggested = {
        key.schema: key.description["suggested_value"]
        for key in result["data_schema"].schema
        if key.description and "suggested_value" in key.description
    }
    assert suggested[CONF_MODEL] == "SDM630"

    with serving(build_unit(SdmModel.SDM630)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_MODEL: SdmModel.SDM630}
        )
        await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_MODEL] == SdmModel.SDM630
    assert config_entry.title == "SDM630 (1)"
    assert config_entry.state is ConfigEntryState.LOADED

    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()


async def test_reconfigure_lets_the_user_keep_their_model(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """The detected model is offered, not imposed.

    The SDM630's meter code is a field report rather than a documented one, so
    a user who chose their model against it must be able to choose it again.
    """
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reconfigure_flow(hass)

    with serving(build_unit(SdmModel.SDM120, meter_code=0x0070)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], SERIAL_INPUT
        )
        assert result["step_id"] == "model_mismatch"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_MODEL: SdmModel.SDM120}
        )
        await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_MODEL] == SdmModel.SDM120
    assert config_entry.state is ConfigEntryState.LOADED

    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()


async def test_reconfigure_does_not_ask_about_a_shared_register_map(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """An SDM120CT reporting the SDM120 code is correctly configured.

    Both read through the same component, so renaming the user's CT to a plain
    SDM120 would change nothing but the device page -- and would undo a
    distinction they made on purpose.
    """
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, CONF_MODEL: SdmModel.SDM120CT}
    )
    result = await config_entry.start_reconfigure_flow(hass)

    with serving(build_unit(meter_code=0x0020)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**SERIAL_INPUT, CONF_UNIT_ID: 3}
        )
        await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_MODEL] == SdmModel.SDM120CT

    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()


async def test_abandoning_the_model_step_does_not_strand_the_entry(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Closing the dialog mid-flow must not leave the meter dark.

    The flow unloads the entry to free the port before probing. Reaching the
    model step means it has been unloaded and not yet put back, so walking
    away there would stop the meter until the next restart.
    """
    config_entry.add_to_hass(hass)
    with serving(build_unit()):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    result = await config_entry.start_reconfigure_flow(hass)
    with serving(build_unit(SdmModel.SDM120, meter_code=0x0070)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], SERIAL_INPUT
        )
        assert result["step_id"] == "model_mismatch"
        assert config_entry.state is ConfigEntryState.NOT_LOADED

        hass.config_entries.flow.async_abort(result["flow_id"])
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.data[CONF_MODEL] == SdmModel.SDM120

    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
