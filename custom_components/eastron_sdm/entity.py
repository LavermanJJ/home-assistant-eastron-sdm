"""Shared entity plumbing for the Eastron SDM integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import SdmCoordinator


class SdmEntity(CoordinatorEntity[SdmCoordinator]):
    """Base for every entity belonging to one meter.

    There is deliberately no ``via_device``: a USB-RS485 converter is not a
    device, it is a path in the connection parameters. Meters sharing a port
    share a connection, not a parent -- so each one stands alone in the
    device registry.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SdmCoordinator,
        description: EntityDescription,
    ) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        self.entity_description = description

        entry = coordinator.config_entry
        info = coordinator.meter.info
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(entry.unique_id))},
            manufacturer=MANUFACTURER,
            model=str(info.model),
            name=entry.title,
            serial_number=(
                str(info.serial_number) if info.serial_number is not None else None
            ),
            sw_version=info.software_version_str,
        )
