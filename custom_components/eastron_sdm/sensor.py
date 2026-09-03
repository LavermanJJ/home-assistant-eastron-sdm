"""Sensor platform for Eastron SDM meters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    DEGREE,
    PERCENTAGE,
    EntityCategory,
    UnitOfApparentPower,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfReactivePower,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SdmConfigEntry
from .entity import SdmEntity
from .sdm import SdmInfo

# Read-only platform behind a coordinator: entities never write to the meter,
# and every request on a port is already serialized behind the shared
# connection's lock. There is nothing here for Home Assistant to throttle.
PARALLEL_UPDATES = 0

MEASUREMENT = SensorStateClass.MEASUREMENT
TOTAL = SensorStateClass.TOTAL
TOTAL_INCREASING = SensorStateClass.TOTAL_INCREASING


@dataclass(frozen=True, kw_only=True)
class SdmSensorEntityDescription(SensorEntityDescription):
    """Describes one measurement sensor.

    ``key`` is the field name on the model's measurement component. The
    platform only creates a sensor when the configured model declares that
    field, so one table serves every model: the SDM630's three-phase fields
    simply do not match on an SDM120.
    """


def _voltage(key: str, *, enabled: bool = True) -> SdmSensorEntityDescription:
    return SdmSensorEntityDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=MEASUREMENT,
        suggested_display_precision=1,
        entity_registry_enabled_default=enabled,
    )


def _current(key: str, *, enabled: bool = True) -> SdmSensorEntityDescription:
    return SdmSensorEntityDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=MEASUREMENT,
        suggested_display_precision=2,
        entity_registry_enabled_default=enabled,
    )


def _power(key: str, *, enabled: bool = True) -> SdmSensorEntityDescription:
    return SdmSensorEntityDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=MEASUREMENT,
        suggested_display_precision=1,
        entity_registry_enabled_default=enabled,
    )


def _apparent_power(key: str, *, enabled: bool = True) -> SdmSensorEntityDescription:
    return SdmSensorEntityDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.APPARENT_POWER,
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        state_class=MEASUREMENT,
        suggested_display_precision=1,
        entity_registry_enabled_default=enabled,
    )


def _reactive_power(key: str, *, enabled: bool = True) -> SdmSensorEntityDescription:
    return SdmSensorEntityDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.REACTIVE_POWER,
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        state_class=MEASUREMENT,
        suggested_display_precision=1,
        entity_registry_enabled_default=enabled,
    )


def _power_factor(key: str, *, enabled: bool = True) -> SdmSensorEntityDescription:
    # Signed: the SDM630 document notes the sign follows current direction,
    # positive forward and negative reverse.
    return SdmSensorEntityDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=MEASUREMENT,
        suggested_display_precision=3,
        entity_registry_enabled_default=enabled,
    )


def _energy(key: str, *, enabled: bool = True) -> SdmSensorEntityDescription:
    # TOTAL_INCREASING rather than TOTAL: these counters only ever climb, and
    # a meter reset should read as a new cycle rather than as negative usage.
    return SdmSensorEntityDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=TOTAL_INCREASING,
        suggested_display_precision=3,
        entity_registry_enabled_default=enabled,
    )


def _reactive_energy(key: str, *, enabled: bool = True) -> SdmSensorEntityDescription:
    return SdmSensorEntityDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.REACTIVE_ENERGY,
        native_unit_of_measurement="kvarh",
        state_class=TOTAL_INCREASING,
        suggested_display_precision=3,
        entity_registry_enabled_default=enabled,
    )


def _angle(key: str) -> SdmSensorEntityDescription:
    return SdmSensorEntityDescription(
        key=key,
        translation_key=key,
        native_unit_of_measurement=DEGREE,
        state_class=MEASUREMENT,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
    )


def _thd(key: str) -> SdmSensorEntityDescription:
    return SdmSensorEntityDescription(
        key=key,
        translation_key=key,
        native_unit_of_measurement=PERCENTAGE,
        state_class=MEASUREMENT,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
    )


#: Every measurement sensor this integration knows how to build, keyed by the
#: model field it reads. Entries with no matching field on the configured
#: model are skipped, so this is the union across all models rather than a
#: per-model table.
#:
#: Enabled by default: what a meter is normally installed to tell you.
#: Disabled by default: harmonics, demand, phase angles and per-phase energy,
#: which the SDM630 offers in bulk and few installations act on. They are
#: still polled -- they share a block read with their neighbours, so leaving
#: them out of the registry costs nothing on the bus and keeps the device
#: page readable.
SENSORS: tuple[SdmSensorEntityDescription, ...] = (
    # --- single phase (SDM120) ---
    _voltage("voltage"),
    _current("current"),
    _power("active_power"),
    _apparent_power("apparent_power"),
    _reactive_power("reactive_power"),
    _power_factor("power_factor"),
    # --- per phase (SDM630) ---
    *(_voltage(f"voltage_l{n}") for n in (1, 2, 3)),
    *(_current(f"current_l{n}") for n in (1, 2, 3)),
    *(_power(f"active_power_l{n}") for n in (1, 2, 3)),
    *(_apparent_power(f"apparent_power_l{n}") for n in (1, 2, 3)),
    *(_reactive_power(f"reactive_power_l{n}") for n in (1, 2, 3)),
    *(_power_factor(f"power_factor_l{n}") for n in (1, 2, 3)),
    *(_angle(f"phase_angle_l{n}") for n in (1, 2, 3)),
    # --- line to line (SDM630) ---
    _voltage("voltage_l1_l2"),
    _voltage("voltage_l2_l3"),
    _voltage("voltage_l3_l1"),
    _voltage("average_voltage_ll"),
    _voltage("average_voltage_ln"),
    _current("neutral_current"),
    # --- system totals ---
    _current("average_current"),
    _current("sum_of_line_currents", enabled=False),
    _power("total_system_power"),
    _apparent_power("total_system_apparent_power"),
    _reactive_power("total_system_reactive_power"),
    _power_factor("total_system_power_factor"),
    _angle("total_system_phase_angle"),
    SdmSensorEntityDescription(
        key="frequency",
        translation_key="frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=MEASUREMENT,
        suggested_display_precision=2,
    ),
    # --- energy ---
    _energy("import_active_energy"),
    _energy("export_active_energy"),
    _energy("total_active_energy"),
    _reactive_energy("import_reactive_energy", enabled=False),
    _reactive_energy("export_reactive_energy", enabled=False),
    _reactive_energy("total_reactive_energy", enabled=False),
    SdmSensorEntityDescription(
        key="total_apparent_energy",
        translation_key="total_apparent_energy",
        native_unit_of_measurement="kVAh",
        state_class=TOTAL_INCREASING,
        suggested_display_precision=3,
        entity_registry_enabled_default=False,
    ),
    SdmSensorEntityDescription(
        key="total_ampere_hours",
        translation_key="total_ampere_hours",
        native_unit_of_measurement="Ah",
        state_class=TOTAL_INCREASING,
        suggested_display_precision=3,
        entity_registry_enabled_default=False,
    ),
    # --- per-phase energy (SDM630) ---
    *(_energy(f"import_active_energy_l{n}", enabled=False) for n in (1, 2, 3)),
    *(_energy(f"export_active_energy_l{n}", enabled=False) for n in (1, 2, 3)),
    *(_energy(f"total_active_energy_l{n}", enabled=False) for n in (1, 2, 3)),
    *(
        _reactive_energy(f"import_reactive_energy_l{n}", enabled=False)
        for n in (1, 2, 3)
    ),
    *(
        _reactive_energy(f"export_reactive_energy_l{n}", enabled=False)
        for n in (1, 2, 3)
    ),
    *(
        _reactive_energy(f"total_reactive_energy_l{n}", enabled=False)
        for n in (1, 2, 3)
    ),
    # --- demand ---
    _power("total_system_power_demand", enabled=False),
    _power("maximum_total_system_power_demand", enabled=False),
    _power("import_system_power_demand", enabled=False),
    _power("maximum_import_system_power_demand", enabled=False),
    _power("export_system_power_demand", enabled=False),
    _power("maximum_export_system_power_demand", enabled=False),
    _apparent_power("total_system_apparent_power_demand", enabled=False),
    _apparent_power("maximum_total_system_apparent_power_demand", enabled=False),
    _reactive_power("total_system_reactive_power_demand", enabled=False),
    _reactive_power("maximum_total_system_reactive_power_demand", enabled=False),
    _current("current_demand", enabled=False),
    _current("maximum_current_demand", enabled=False),
    *(_current(f"current_demand_l{n}", enabled=False) for n in (1, 2, 3)),
    *(_current(f"maximum_current_demand_l{n}", enabled=False) for n in (1, 2, 3)),
    _current("neutral_current_demand", enabled=False),
    _current("maximum_neutral_current_demand", enabled=False),
    # --- single-phase phase angle (SDM230) ---
    _angle("phase_angle"),
    # --- resettable counters (SDM72D, SDM630MCT) ---
    # Zeroed from the meter's own menu, which TOTAL_INCREASING handles as the
    # start of a new cycle rather than as negative usage -- the same reason
    # the lifetime totals use it.
    _energy("resettable_total_active_energy", enabled=False),
    _energy("resettable_import_active_energy", enabled=False),
    _energy("resettable_export_active_energy", enabled=False),
    _reactive_energy("resettable_total_reactive_energy", enabled=False),
    _reactive_energy("resettable_import_reactive_energy", enabled=False),
    _reactive_energy("resettable_export_reactive_energy", enabled=False),
    # Import minus export, so it falls whenever export runs ahead. TOTAL, not
    # TOTAL_INCREASING, which would read every fall as a meter reset.
    SdmSensorEntityDescription(
        key="net_active_energy",
        translation_key="net_active_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=TOTAL,
        suggested_display_precision=3,
    ),
    # --- directional system power (SDM72D) ---
    _power("total_import_active_power"),
    _power("total_export_active_power"),
    # --- harmonics ---
    *(_thd(f"voltage_thd_l{n}") for n in (1, 2, 3)),
    *(_thd(f"current_thd_l{n}") for n in (1, 2, 3)),
    _thd("average_voltage_thd_ln"),
    _thd("average_current_thd"),
    _thd("voltage_thd_l1_l2"),
    _thd("voltage_thd_l2_l3"),
    _thd("voltage_thd_l3_l1"),
    _thd("average_voltage_thd_ll"),
)


@dataclass(frozen=True, kw_only=True)
class SdmDiagnosticEntityDescription(SensorEntityDescription):
    """Describes a diagnostic sensor read from the meter's identity block."""

    value_fn: Callable[[SdmInfo], str | int | None]


DIAGNOSTICS: tuple[SdmDiagnosticEntityDescription, ...] = (
    SdmDiagnosticEntityDescription(
        key="node_address",
        translation_key="node_address",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda info: info.node_address,
    ),
    SdmDiagnosticEntityDescription(
        key="baud_rate",
        translation_key="baud_rate",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda info: info.baud_rate,
    ),
    SdmDiagnosticEntityDescription(
        key="line_settings",
        translation_key="line_settings",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda info: (
            f"8{info.parity}{info.stopbits}" if info.parity is not None else None
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SdmConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors for one meter."""
    coordinator = entry.runtime_data
    declared = coordinator.meter.measurements.declared_fields

    entities: list[SensorEntity] = [
        SdmSensor(coordinator, description)
        for description in SENSORS
        if description.key in declared
    ]
    # Created unconditionally. The identity read is allowed to fail -- a busy
    # bus at startup is not a reason to refuse setup -- and filtering on the
    # value here would make the entity set depend on whether that happened to
    # succeed, leaving entities permanently absent until the entry reloads.
    entities.extend(
        SdmDiagnosticSensor(coordinator, description) for description in DIAGNOSTICS
    )
    async_add_entities(entities)


class SdmSensor(SdmEntity, SensorEntity):
    """One measurement read straight off the polled model."""

    entity_description: SdmSensorEntityDescription

    @property
    def native_value(self) -> float | None:
        """Return the last decoded value of this field."""
        return self.coordinator.meter.value(self.entity_description.key)


class SdmDiagnosticSensor(SdmEntity, SensorEntity):
    """A value from the meter's identity block, read once at setup.

    Not refreshed by the coordinator: these change only when someone
    reconfigures the meter, at which point it needs a restart anyway.
    """

    entity_description: SdmDiagnosticEntityDescription

    @property
    def native_value(self) -> str | int | None:
        """Return the stored identity value."""
        return self.entity_description.value_fn(self.coordinator.meter.info)

    @property
    def available(self) -> bool:
        """Identity values survive a failed poll, unlike measurements."""
        return True
