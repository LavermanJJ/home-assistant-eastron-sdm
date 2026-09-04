"""Tests for the register model, which is where a transcription slip hides."""

from __future__ import annotations

from modbus_connection.exceptions import IllegalDataAddressError, ModbusTimeoutError
import pytest

from custom_components.eastron_sdm.sdm import (
    MEASUREMENTS,
    METER_CODES,
    SdmMeter,
    SdmModel,
    async_probe,
)

from .conftest import SERIAL_NUMBER, build_unit

#: The per-request ceiling each model's protocol document states, in
#: registers. Duplicated from the documents on purpose: asserting that a read
#: fits inside ``max_span`` only proves the planner honours the number it was
#: given, so the number itself has to be pinned against the paperwork.
#:
#:   80  "maximum of 40 values in a single transaction; therefore the maximum
#:        number of registers requestable is 80"
#:   60  "Each request for data must be restricted to 30 parameters or less"
DOCUMENTED_LIMITS = {
    SdmModel.SDM120: 80,
    SdmModel.SDM120CT: 80,
    SdmModel.SDM230: 80,
    SdmModel.SDM630: 80,
    SdmModel.SDM630MCT: 60,
    SdmModel.SDM72D_M_1: 60,
    SdmModel.SDM72DM_V2: 60,
}


@pytest.mark.parametrize("model", list(SdmModel))
def test_max_span_matches_the_protocol_document(model: SdmModel) -> None:
    """The declared limit must be the one the manual states.

    This is the assertion that actually holds the SDM72D pair and the
    SDM630MCT to 60 registers. Raising one of them back to the SDM630's 80
    would sail past a read-fits-in-max_span check while real hardware
    rejected the block and took the whole poll down with it.
    """
    assert MEASUREMENTS[model].max_span == DOCUMENTED_LIMITS[model]


@pytest.mark.parametrize("model", list(SdmModel))
async def test_every_block_read_is_legal(model: SdmModel) -> None:
    """Reads must obey the limits the Eastron protocol documents.

    Section 1.2 of the SDM630 document: a start address and a register count
    must both be even, because every parameter is a float spanning two
    registers.

    The per-request ceiling is not the same across the range: the SDM120,
    SDM120CT, SDM230 and SDM630 allow 40 values (80 registers), while the
    SDM72D pair and the SDM630MCT allow only 30 (60). So each model is checked
    against its own declared limit -- asserting the most generous one would
    pass a request the stricter meters reject.
    """
    limit = MEASUREMENTS[model].max_span
    assert limit <= 80, "80 registers is the most any SDM documents"

    unit = build_unit(model)
    meter = SdmMeter(unit, model)
    await meter.async_setup()
    unit.read_events.clear()
    await meter.async_update()

    assert unit.read_events
    for event in unit.read_events:
        assert event.address % 2 == 0, f"odd start address 0x{event.address:04X}"
        assert event.count % 2 == 0, f"odd register count {event.count}"
        assert event.count <= limit, (
            f"{event.count} registers exceeds this model's {limit} limit"
        )


@pytest.mark.parametrize(
    ("model", "expected_reads"),
    [
        (SdmModel.SDM120, 4),
        (SdmModel.SDM120CT, 4),
        (SdmModel.SDM230, 4),
        (SdmModel.SDM630, 4),
        (SdmModel.SDM630MCT, 6),
        (SdmModel.SDM72D_M_1, 6),
        (SdmModel.SDM72DM_V2, 6),
    ],
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


async def test_probe_identifies_the_field_reported_sdm120_code() -> None:
    """0x0004 selects the SDM120, so that variant is not asked for its model."""
    probe = await async_probe(build_unit(SdmModel.SDM120, meter_code=0x0004))

    assert probe.model is SdmModel.SDM120
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


def test_sdm120ct_shares_the_sdm120_map() -> None:
    """The CT variant changes how current is sensed, not which registers report it.

    Its protocol document lists the same twenty-one addresses, so it shares the
    component rather than duplicating the table -- while keeping its own model
    name, which is what the device page shows.
    """
    assert MEASUREMENTS[SdmModel.SDM120CT] is MEASUREMENTS[SdmModel.SDM120]


def test_sdm230_is_the_sdm120_map_plus_phase_angle() -> None:
    """Stated as a subclass, so the difference is the whole declaration."""
    sdm120 = set(MEASUREMENTS[SdmModel.SDM120].declared_fields)
    sdm230 = set(MEASUREMENTS[SdmModel.SDM230].declared_fields)

    assert sdm230 - sdm120 == {"phase_angle"}
    assert not sdm120 - sdm230


def test_sdm630mct_extends_the_sdm630_map() -> None:
    """The MCT adds reactive power demand and the resettable counters."""
    sdm630 = set(MEASUREMENTS[SdmModel.SDM630].declared_fields)
    mct = set(MEASUREMENTS[SdmModel.SDM630MCT].declared_fields)

    assert mct - sdm630 == {
        "total_system_reactive_power_demand",
        "maximum_total_system_reactive_power_demand",
        "resettable_total_active_energy",
        "resettable_total_reactive_energy",
        "resettable_import_active_energy",
        "resettable_export_active_energy",
        "resettable_import_reactive_energy",
        "resettable_export_reactive_energy",
    }
    assert not sdm630 - mct


def test_the_two_sdm72d_meters_are_not_interchangeable() -> None:
    """They share a name and a meter-code neighbourhood but not a register map.

    The -M-1 is an energy meter with no voltage or current at all; picking the
    wrong one would leave most entities permanently unavailable.
    """
    m1 = set(MEASUREMENTS[SdmModel.SDM72D_M_1].declared_fields)
    v2 = set(MEASUREMENTS[SdmModel.SDM72DM_V2].declared_fields)

    assert "voltage_l1" not in m1
    assert "voltage_l1" in v2
    assert m1 - v2 == set(), "the -M-1 measures nothing the V2 does not"


def test_no_meter_code_resolves_to_two_models() -> None:
    """A code must not resolve to two models, or detection is a coin toss.

    The mapping is deliberately not injective the other way: one model may
    report several codes across firmware revisions and OEM variants, which is
    why ``SDM120`` appears under both its documented ``0x0020`` and the
    field-reported ``0x0004``. Only every value being a real model matters.
    """
    assert set(METER_CODES.values()) <= set(SdmModel)
