"""Tests for the register model, which is where a transcription slip hides."""

from __future__ import annotations

from modbus_connection.exceptions import IllegalDataAddressError, ModbusTimeoutError
import pytest

from custom_components.eastron_sdm.sdm import (
    MEASUREMENTS,
    SdmMeter,
    SdmModel,
    async_probe,
)

from .conftest import SERIAL_NUMBER, build_unit


@pytest.mark.parametrize("model", list(SdmModel))
async def test_every_block_read_is_legal(model: SdmModel) -> None:
    """Reads must obey the limits the Eastron protocol documents.

    Section 1.2 of the SDM630 document: a start address and a register count
    must both be even, because every parameter is a float spanning two
    registers, and no request may exceed 80 registers.
    """
    unit = build_unit(model)
    meter = SdmMeter(unit, model)
    await meter.async_setup()
    unit.read_events.clear()
    await meter.async_update()

    assert unit.read_events
    for event in unit.read_events:
        assert event.address % 2 == 0, f"odd start address 0x{event.address:04X}"
        assert event.count % 2 == 0, f"odd register count {event.count}"
        assert event.count <= 80, f"{event.count} registers exceeds the 80 limit"


@pytest.mark.parametrize(
    ("model", "expected_reads"), [(SdmModel.SDM120, 4), (SdmModel.SDM630, 4)]
)
async def test_poll_is_a_handful_of_reads(model: SdmModel, expected_reads: int) -> None:
    """A poll must not degrade into one request per field.

    Six meters on one bus share a connection, so read count is the budget
    that decides whether a short scan interval is viable at all.
    """
    unit = build_unit(model)
    meter = SdmMeter(unit, model)
    await meter.async_setup()
    unit.read_events.clear()
    await meter.async_update()

    assert len(unit.read_events) == expected_reads


@pytest.mark.parametrize("model", list(SdmModel))
async def test_every_field_decodes_to_its_own_value(model: SdmModel) -> None:
    """Each field must decode the registers at its own address, not a neighbour's."""
    unit = build_unit(model)
    meter = SdmMeter(unit, model)
    await meter.async_update()

    for index, name in enumerate(MEASUREMENTS[model].declared_fields):
        assert meter.value(name) == pytest.approx(index + 1), name


async def test_word_order_is_big_endian() -> None:
    """A swapped word order yields a plausible wrong number, so pin it down.

    230.2 encodes as 0x4366 0x3334; reversed it decodes to about 1.9e-19.
    The value here is the worked example from the SDM120 document.
    """
    unit = build_unit(SdmModel.SDM120)
    unit.input[0x0000] = [0x4366, 0x3334]
    meter = SdmMeter(unit, SdmModel.SDM120)
    await meter.async_update()

    assert meter.value("voltage") == pytest.approx(230.2, abs=0.01)


async def test_identity_is_read_once_at_setup() -> None:
    """Setup must collect serial number, firmware and link settings."""
    unit = build_unit(SdmModel.SDM120)
    meter = SdmMeter(unit, SdmModel.SDM120)
    await meter.async_setup()

    assert meter.info.serial_number == SERIAL_NUMBER
    assert meter.info.software_version_str == "1.4"
    assert meter.info.node_address == 1
    assert meter.info.baud_rate == 9600
    assert (meter.info.parity, meter.info.stopbits) == ("N", 1)


async def test_missing_device_info_block_does_not_break_setup() -> None:
    """An SDM630 that does not serve 0xFC00 must still set up.

    The V1.8 document never promised that block, so a meter refusing it is
    within spec and its measurements are still readable.
    """
    unit = build_unit(SdmModel.SDM630)
    unit.fail_read(0xFC00, IllegalDataAddressError(), register_type="holding")

    meter = SdmMeter(unit, SdmModel.SDM630)
    await meter.async_setup()

    assert meter.info.serial_number is None
    assert meter.info.node_address == 1  # the documented block still answered

    await meter.async_update()
    assert meter.value("voltage_l1") == pytest.approx(1)


async def test_probe_identifies_a_known_meter_code() -> None:
    """The documented SDM120 meter code selects the model."""
    probe = await async_probe(build_unit(SdmModel.SDM120, meter_code=0x0020))

    assert probe.model is SdmModel.SDM120
    assert probe.serial_number == SERIAL_NUMBER
    assert probe.identified


async def test_probe_leaves_an_unknown_meter_code_to_the_user() -> None:
    """An unrecognised code means "ask", not "unsupported"."""
    probe = await async_probe(build_unit(SdmModel.SDM120, meter_code=0x00FF))

    assert probe.model is None
    assert probe.serial_number == SERIAL_NUMBER
    assert not probe.identified


async def test_probe_propagates_a_dead_bus() -> None:
    """Nothing answering must reach the caller as a Modbus error."""
    unit = build_unit(SdmModel.SDM120)
    unit.fail_requests(ModbusTimeoutError())

    with pytest.raises(ModbusTimeoutError):
        await async_probe(unit)
