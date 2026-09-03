"""Poll one Eastron SDM meter."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from modbus_connection import ModbusError

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .sdm import SdmMeter

_LOGGER = logging.getLogger(__name__)

type SdmConfigEntry = ConfigEntry[SdmCoordinator]


class SdmCoordinator(DataUpdateCoordinator[None]):
    """Drive one meter's polling.

    Holds no data of its own: the meter object stores the decoded values and
    entities read them straight off it. The coordinator exists for the
    schedule, the shared failure handling, and the availability signal.
    """

    config_entry: SdmConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: SdmConfigEntry,
        meter: SdmMeter,
    ) -> None:
        """Initialise the coordinator."""
        scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=entry.title,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.meter = meter

    async def _async_update_data(self) -> None:
        """Read every measurement register for this meter."""
        try:
            await self.meter.async_update()
        except ModbusError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="poll_failed",
                translation_placeholders={"error": str(err)},
            ) from err
