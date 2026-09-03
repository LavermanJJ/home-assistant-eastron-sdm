"""The Eastron SDM integration."""

from __future__ import annotations

from homeassistant.components.modbus import async_get_unit
from homeassistant.const import CONF_MODEL, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError, HomeAssistantError
from homeassistant.helpers import issue_registry as ir

from .connection import build_params
from .const import CONF_UNIT_ID, DOMAIN
from .coordinator import SdmConfigEntry, SdmCoordinator
from .sdm import SdmMeter, SdmModel, contradicting_model

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: SdmConfigEntry) -> bool:
    """Set up one Eastron SDM meter from a config entry."""
    data = dict(entry.data)
    try:
        params = build_params(data)
        model = SdmModel(data[CONF_MODEL])
        unit_id = int(data[CONF_UNIT_ID])
    except (KeyError, TypeError, ValueError) as err:
        raise ConfigEntryError(
            translation_domain=DOMAIN, translation_key="invalid_entry"
        ) from err

    try:
        # Hands back a unit on a connection shared with every other entry
        # addressing the same port or host, and registers its own release on
        # entry unload. The connection is not ours to open or close.
        unit = async_get_unit(hass, entry, params, unit_id)
    except HomeAssistantError as err:
        # The port is already open with different line settings. Retrying
        # cannot fix that -- one of the two entries has to be corrected.
        raise ConfigEntryError(
            translation_domain=DOMAIN,
            translation_key="bus_settings_conflict",
            translation_placeholders={"error": str(err)},
        ) from err

    meter = SdmMeter(unit, model)
    # Never raises: identity is optional, and a meter that does not answer is
    # caught by the first coordinator refresh below.
    await meter.async_setup()

    _async_check_model(hass, entry, meter, model)

    coordinator = SdmCoordinator(hass, entry, meter)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def _model_issue_id(entry: SdmConfigEntry) -> str:
    """Name the model-mismatch repair issue for one entry."""
    return f"model_mismatch_{entry.entry_id}"


@callback
def _async_check_model(
    hass: HomeAssistant,
    entry: SdmConfigEntry,
    meter: SdmMeter,
    model: SdmModel,
) -> None:
    """Raise a repair issue if the meter contradicts the configured model.

    The entry still loads. A mismatch reads the wrong registers and decodes
    them into plausible numbers rather than into an error, so it has to be
    visible somewhere the user will actually meet it -- but the user may also
    know better than the meter code, and taking their meter away over it would
    be worse than letting it run.

    Raised and cleared on every setup, so accepting the reconfigure flow's
    correction retires the issue with no further bookkeeping.
    """
    if (code := meter.info.meter_code) is None or (
        detected := contradicting_model(code, model)
    ) is None:
        ir.async_delete_issue(hass, DOMAIN, _model_issue_id(entry))
        return

    ir.async_create_issue(
        hass,
        DOMAIN,
        _model_issue_id(entry),
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="model_mismatch",
        translation_placeholders={
            "name": entry.title,
            "configured": str(model),
            "detected": str(detected),
            "meter_code": f"0x{code:04X}",
        },
    )


async def async_remove_entry(hass: HomeAssistant, entry: SdmConfigEntry) -> None:
    """Retire this entry's repair issue along with the entry itself.

    Issues outlive the config entry that raised them, and one about a meter
    that is no longer set up cannot be acted on.
    """
    ir.async_delete_issue(hass, DOMAIN, _model_issue_id(entry))


async def async_unload_entry(hass: HomeAssistant, entry: SdmConfigEntry) -> bool:
    """Unload a config entry.

    The Modbus unit releases itself through the callback ``async_get_unit``
    registered on the entry, closing the shared connection only once the last
    meter on that port has gone.
    """
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
