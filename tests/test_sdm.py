"""Tests for the register model, which is where a transcription slip hides."""

from __future__ import annotations

from modbus_connection.exceptions import IllegalDataAddressError, ModbusTimeoutError
import pytest

from custom_components.eastron_sdm.sdm import (
    MEASUREMENTS,
    METER_CODES,
    PROVISIONAL_METER_CODES,
    SdmMeter,
    SdmModel,
    async_ping,
    async_probe,
    contradicting_model,
    provisional_model,
)

from .conftest import SERIAL_NUMBER, build_unit, encode_float

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


async def test_non_finite_link_settings_do_not_break_setup() -> None:
    """Garbage in the network block must not escape setup as a traceback.

    A device that is not an SDM -- another make answering a unit ID typed by
    mistake -- can leave any bit pattern in those three floats. NaN and
    infinity both make a bare ``int()`` raise, and neither exception is a
    ``ModbusError``, so one would escape ``async_setup`` past every handler
    written for a meter that does not answer.
    """
    unit = build_unit(SdmModel.SDM120)
    unit.holding[0x0012] = encode_float(float("inf"))
    unit.holding[0x0014] = encode_float(float("nan"))
    unit.holding[0x001C] = encode_float(float("-inf"))

    meter = SdmMeter(unit, SdmModel.SDM120)
    await meter.async_setup()

    assert meter.info.node_address is None
    assert meter.info.baud_rate is None
    assert (meter.info.parity, meter.info.stopbits) == (None, None)
    # The identity block is a separate read and is unaffected by the garbage.
    assert meter.info.serial_number == SERIAL_NUMBER


@pytest.mark.parametrize("node", [float("nan"), float("inf"), 0.0, 248.0, -1.0])
async def test_ping_rejects_a_node_address_no_sdm_could_report(node: float) -> None:
    """``async_ping`` must not vouch for a device answering nonsense.

    Every SDM documents this register and every one reports 1..247 in it, so
    anything else is evidence that whatever is at this address is a different
    device. Answering "yes, a meter" would hand the user an entry decoding
    every reading from registers that mean something else on that hardware.
    """
    unit = build_unit(SdmModel.SDM120)
    unit.holding[0x0014] = encode_float(node)

    assert await async_ping(unit) is None


async def test_ping_accepts_a_real_node_address() -> None:
    """A meter answering the documented block is confirmed alive."""
    assert await async_ping(build_unit(SdmModel.SDM120)) == 1


async def test_probe_identifies_a_known_meter_code() -> None:
    """The documented SDM120 meter code selects the model."""
    probe = await async_probe(build_unit(SdmModel.SDM120, meter_code=0x0020))

    assert probe.model is SdmModel.SDM120
    assert probe.serial_number == SERIAL_NUMBER
    assert probe.identified


async def test_a_provisional_code_does_not_configure_on_its_own() -> None:
    """0x0004 must reach the user, not decide.

    Probing has to leave ``model`` unset or the config flow skips the model
    step entirely, configuring on one field report a meter whose own manual
    documents a different code. The SDM230 is the reason: its manual documents
    no meter code at all, so nothing rules out an SDM230 reporting 0x0004, and
    it does not share the SDM120 register map.
    """
    probe = await async_probe(build_unit(SdmModel.SDM120, meter_code=0x0004))

    assert probe.model is None
    assert not probe.identified
    assert provisional_model(probe.meter_code) is SdmModel.SDM120


def test_provisional_codes_stay_out_of_the_deciding_table() -> None:
    """The two tables must not overlap, or a provisional code would decide."""
    assert not set(PROVISIONAL_METER_CODES) & set(METER_CODES)
    assert set(PROVISIONAL_METER_CODES.values()) <= set(MEASUREMENTS)


def test_a_contradiction_is_never_raised_from_a_provisional_code() -> None:
    """A provisional code must not accuse a correct entry of being wrong.

    ``0x0004`` on an entry the user set up as an SDM230 by hand would raise a
    permanent mismatch repair issue against hardware that is configured right,
    which is the cost of letting an unverified code into ``METER_CODES``.
    """
    for model in SdmModel:
        assert contradicting_model(0x0004, model) is None


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
    # `<= set(SdmModel)` would restate the dict annotation and prove nothing.
    # Every value having a register map is the real load: `contradicting_model`
    # indexes MEASUREMENTS with whatever comes out of here, unguarded.
    assert set(METER_CODES.values()) <= set(MEASUREMENTS)
