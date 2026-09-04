"""Tests for the button platform, the one place this integration writes."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from modbus_connection.exceptions import IllegalDataAddressError
from modbus_connection.mock import WriteEvent
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eastron_sdm.const import CONF_UNIT_ID, DOMAIN
from custom_components.eastron_sdm.sdm import (
    DEMAND_RESET_MODELS,
    DEMAND_RESET_REGISTER,
    DEMAND_RESET_VALUE,
    MEASUREMENTS,
    SdmMeter,
    SdmModel,
)

from .conftest import SERIAL_DATA, build_unit

BUTTON = "button.sdm630_1_reset_maximum_demand"


def _entry(model: SdmModel) -> MockConfigEntry:
    """Build an entry for one model on unit 1."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={**SERIAL_DATA, "model": model, CONF_UNIT_ID: 1},
        unique_id="82600529",
        title=f"{model} (1)",
    )


async def _setup(hass: HomeAssistant, model: SdmModel, unit) -> None:
    entry = _entry(model)
    entry.add_to_hass(hass)
    with patch("custom_components.eastron_sdm.async_get_unit", return_value=unit):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


async def test_pressing_writes_the_documented_register(hass: HomeAssistant) -> None:
    """The press must write 0x0000 to 0xF010, and nothing else.

    Pinned against the SDM630 protocol document rather than against whatever
    the code currently does: this is the integration's only write, onto a bus
    whose other holding registers set the node address, the baud rate and the
    pulse output. A slip here reconfigures someone's meter.
    """
    unit = build_unit(SdmModel.SDM630)
    await _setup(hass, SdmModel.SDM630, unit)

    # Registered after setup, so setup writing anything at all would still be
    # caught by the "exactly one write" assertion below.
    writes: list[WriteEvent] = []
    unit.on_write(writes.append)

    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: BUTTON}, blocking=True
    )

    assert len(writes) == 1
    event = writes[0]
    assert event.address == DEMAND_RESET_REGISTER == 0xF010
    assert event.values == [DEMAND_RESET_VALUE] == [0x0000]
    assert event.register_type == "holding"
    # "Function code 10 to set holding parameter" is FC16, not FC06.
    assert event.function_code == 0x10


async def test_a_failed_write_is_reported_not_swallowed(hass: HomeAssistant) -> None:
    """A meter refusing the register must surface, not look like success."""
    unit = build_unit(SdmModel.SDM630)
    await _setup(hass, SdmModel.SDM630, unit)
    unit.fail_write(
        DEMAND_RESET_REGISTER, IllegalDataAddressError(), register_type="holding"
    )

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: BUTTON}, blocking=True
        )


async def test_the_sdm120_is_offered_the_reset_on_a_field_trial(
    hass: HomeAssistant,
) -> None:
    """The SDM120 gets the button although its manual documents no register.

    Pinned deliberately. The address comes from the SDM630 document and the
    SDM120's own table never mentions it, so this entry rests on a decision
    rather than on paperwork -- and withdrawing it after a failed trial should
    mean editing a test that says so, not quietly dropping a set member.
    """
    unit = build_unit(SdmModel.SDM120)
    await _setup(hass, SdmModel.SDM120, unit)

    writes: list[WriteEvent] = []
    unit.on_write(writes.append)

    await hass.services.async_call(
        BUTTON_DOMAIN,
        SERVICE_PRESS,
        {ATTR_ENTITY_ID: "button.sdm120_1_reset_maximum_demand"},
        blocking=True,
    )

    assert [(e.address, e.values) for e in writes] == [(0xF010, [0x0000])]


@pytest.mark.parametrize("model", [m for m in SdmModel if m not in DEMAND_RESET_MODELS])
async def test_no_button_where_the_register_is_undocumented(
    hass: HomeAssistant, model: SdmModel
) -> None:
    """Models without a documented reset register get no button at all.

    Offering one would mean writing to an address the manufacturer never
    published, on hardware that may be billing someone.
    """
    unit = build_unit(model)
    await _setup(hass, model, unit)

    assert not [
        state
        for state in hass.states.async_all(BUTTON_DOMAIN)
        if state.entity_id.startswith("button.")
    ]


@pytest.mark.parametrize("model", list(SdmModel))
async def test_the_library_refuses_an_undocumented_reset(model: SdmModel) -> None:
    """``async_reset_demand`` must not guess an address from a sibling model."""
    meter = SdmMeter(build_unit(model), model)

    if model in DEMAND_RESET_MODELS:
        await meter.async_reset_demand()
    else:
        with pytest.raises(ValueError, match="documents no demand-reset register"):
            await meter.async_reset_demand()


def test_every_model_with_a_reset_has_a_register_map() -> None:
    """A model cannot be resettable without otherwise being supported."""
    assert set(MEASUREMENTS) >= DEMAND_RESET_MODELS
