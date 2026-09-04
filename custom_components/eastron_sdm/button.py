"""Button platform for Eastron SDM meters."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from modbus_connection import ModbusError

from .const import DOMAIN
from .coordinator import SdmConfigEntry
from .entity import SdmEntity

# The only platform that writes. One button per meter, and every request on a
# port is already serialized behind the shared connection's lock, so this is
# about intent rather than throughput: a reset is a discrete action a person
# takes, and letting Home Assistant fan several out at once across a bus would
# interleave them with the polls of every other meter sharing the port.
PARALLEL_UPDATES = 1

RESET_DEMAND = ButtonEntityDescription(
    key="reset_demand",
    translation_key="reset_demand",
    entity_category=EntityCategory.CONFIG,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SdmConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the buttons for one meter.

    Nothing is created for a model whose protocol document does not describe
    the reset register. A button that cannot be pressed without writing to an
    address the manufacturer never published is worse than no button.
    """
    coordinator = entry.runtime_data
    if not coordinator.meter.supports_demand_reset:
        return
    async_add_entities([SdmResetDemandButton(coordinator, RESET_DEMAND)])


class SdmResetDemandButton(SdmEntity, ButtonEntity):
    """Clears the meter's maximum-demand readings."""

    entity_description: ButtonEntityDescription

    async def async_press(self) -> None:
        """Reset the maxima on the meter itself.

        The values are held by the meter, not accumulated here, so there is
        nothing to refresh afterwards: the next poll reads the cleared figures
        the same way it read the old ones.
        """
        try:
            await self.coordinator.meter.async_reset_demand()
        except ModbusError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="reset_demand_failed",
                translation_placeholders={"error": str(err)},
            ) from err
