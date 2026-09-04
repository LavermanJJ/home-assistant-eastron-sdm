"""Tests for icons.json, which the sensor table cannot enforce on its own."""

from __future__ import annotations

import json
import pathlib

from homeassistant.components.sensor import SensorDeviceClass
import pytest

from custom_components.eastron_sdm.sensor import DIAGNOSTICS, SENSORS

#: Device classes whose Home Assistant default is a bolt or a flash. Every one
#: of these is an accumulating meter reading in this integration, and a bolt
#: reads as instantaneous flow -- which is what the *power* sensors are, and
#: what these are not.
COUNTER_CLASSES = (SensorDeviceClass.ENERGY, SensorDeviceClass.REACTIVE_ENERGY)

ICONS: dict[str, dict[str, str]] = json.loads(
    (
        pathlib.Path(__file__).parent.parent
        / "custom_components/eastron_sdm/icons.json"
    ).read_text()
)["entity"]["sensor"]


@pytest.mark.parametrize(
    "key",
    [d.key for d in SENSORS if d.device_class in COUNTER_CLASSES],
)
def test_every_energy_counter_has_a_meter_icon(key: str) -> None:
    """An energy reading must not fall back to Home Assistant's bolt."""
    assert key in ICONS, f"{key} would fall back to mdi:lightning-bolt"
    assert ICONS[key]["default"].startswith("mdi:meter-electric")


def test_instantaneous_sensors_keep_their_own_iconography() -> None:
    """Power is a flow, not a meter reading, so it keeps the flash.

    Overriding it too would lose the one visual cue that separates "how much
    right now" from "how much since the meter was installed" on a device page
    that lists both next to each other.
    """
    power = {SensorDeviceClass.POWER, SensorDeviceClass.APPARENT_POWER}
    for description in SENSORS:
        if description.device_class in power:
            assert description.key not in ICONS


def test_no_icon_is_declared_for_a_sensor_that_does_not_exist() -> None:
    """A stale key is dead weight that reads like a promise."""
    known = {d.key for d in SENSORS} | {d.key for d in DIAGNOSTICS}
    assert set(ICONS) <= known, f"unknown icon keys: {set(ICONS) - known}"
