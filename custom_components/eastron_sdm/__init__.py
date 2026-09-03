"""The Eastron SDM integration."""

from __future__ import annotations

import logging

from homeassistant.components.modbus import async_get_unit
from homeassistant.const import CONF_MODEL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError, HomeAssistantError

from .connection import build_params
from .const import CONF_UNIT_ID, DOMAIN
from .coordinator import SdmConfigEntry, SdmCoordinator
from .sdm import METER_CODES, SdmMeter, SdmModel

_LOGGER = logging.getLogger(__name__)

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

    if (code := meter.info.meter_code) is not None:
        detected = METER_CODES.get(code)
        if detected is not None and detected is not model:
            _LOGGER.warning(
                "%s is configured as %s but reports meter code 0x%04X (%s). "
                "Reconfigure the entry if the wrong model was chosen",
                entry.title,
                model,
                code,
                detected,
            )

    coordinator = SdmCoordinator(hass, entry, meter)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SdmConfigEntry) -> bool:
    """Unload a config entry.

    The Modbus unit releases itself through the callback ``async_get_unit``
    registered on the entry, closing the shared connection only once the last
    meter on that port has gone.
    """
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
