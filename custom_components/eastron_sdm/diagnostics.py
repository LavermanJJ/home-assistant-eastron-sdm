"""Diagnostics for the Eastron SDM integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_DEVICE, CONF_HOST
from homeassistant.core import HomeAssistant

from .coordinator import SdmConfigEntry

# The serial device path and gateway host say where the user's hardware lives;
# neither is needed to reason about a bug report.
TO_REDACT = {CONF_DEVICE, CONF_HOST, "serial_number"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SdmConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for one meter."""
    coordinator = entry.runtime_data
    meter = coordinator.meter
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "info": async_redact_data(asdict(meter.info), TO_REDACT),
        "last_update_success": coordinator.last_update_success,
        "values": {field: meter.value(field) for field in meter.fields},
    }
