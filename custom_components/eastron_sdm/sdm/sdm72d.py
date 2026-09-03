"""SDM72D input registers (FC04).

Two different meters share the SDM72D name and they are not interchangeable:

* ``Sdm72dMeasurements`` follows *Eastron SDM72D-M-1 User Manual V1.4*, which
  reports meter code 0x0084. It is an energy meter, not an analyser: twelve
  parameters, no voltage, no current, no power factor.
* ``Sdm72dmV2Measurements`` follows *Eastron SDM72DM-V2 User Manual V1.1*,
  meter code 0x0089, which measures the full three-phase set but still leaves
  out the SDM630's phase angles, harmonics, demand figures and per-phase
  energy.

Both cap a request at 30 parameters, not the SDM630's 40: "Each request for
data must be restricted to 30 parameters or less." See ``docs/README.md``.
"""

from __future__ import annotations

from modbus_connection.model import Component, float32


class Sdm72dMeasurements(Component):
    """Every documented SDM72D-M-1 measurement."""

    register_space = "input"
    max_span = 60
    register_ranges = (
        (0x000C, 0x0035),
        (0x0048, 0x004B),
        (0x0156, 0x0157),
        (0x0180, 0x0187),
        (0x0500, 0x0503),
    )

    active_power_l1 = float32(0x000C, unit="W")
    active_power_l2 = float32(0x000E, unit="W")
    active_power_l3 = float32(0x0010, unit="W")
    total_system_power = float32(0x0034, unit="W")

    import_active_energy = float32(0x0048, unit="kWh")
    export_active_energy = float32(0x004A, unit="kWh")
    # Note 1 in the manual: total kWh is import + export.
    total_active_energy = float32(0x0156, unit="kWh")

    # Counters the user can zero from the meter, unlike the totals above.
    resettable_total_active_energy = float32(0x0180, unit="kWh")
    resettable_import_active_energy = float32(0x0184, unit="kWh")
    resettable_export_active_energy = float32(0x0186, unit="kWh")

    total_import_active_power = float32(0x0500, unit="W")
    total_export_active_power = float32(0x0502, unit="W")


class Sdm72dmV2Measurements(Component):
    """Every documented SDM72DM-V2 measurement."""

    register_space = "input"
    max_span = 60
    register_ranges = (
        (0x0000, 0x004B),
        (0x00C8, 0x00E1),
        (0x0156, 0x0159),
        (0x0180, 0x018D),
        (0x0500, 0x0503),
    )

    voltage_l1 = float32(0x0000, unit="V")
    voltage_l2 = float32(0x0002, unit="V")
    voltage_l3 = float32(0x0004, unit="V")
    current_l1 = float32(0x0006, unit="A")
    current_l2 = float32(0x0008, unit="A")
    current_l3 = float32(0x000A, unit="A")
    active_power_l1 = float32(0x000C, unit="W")
    active_power_l2 = float32(0x000E, unit="W")
    active_power_l3 = float32(0x0010, unit="W")
    apparent_power_l1 = float32(0x0012, unit="VA")
    apparent_power_l2 = float32(0x0014, unit="VA")
    apparent_power_l3 = float32(0x0016, unit="VA")
    reactive_power_l1 = float32(0x0018, unit="var")
    reactive_power_l2 = float32(0x001A, unit="var")
    reactive_power_l3 = float32(0x001C, unit="var")
    power_factor_l1 = float32(0x001E)
    power_factor_l2 = float32(0x0020)
    power_factor_l3 = float32(0x0022)

    average_voltage_ln = float32(0x002A, unit="V")
    average_current = float32(0x002E, unit="A")
    sum_of_line_currents = float32(0x0030, unit="A")
    total_system_power = float32(0x0034, unit="W")
    total_system_apparent_power = float32(0x0038, unit="VA")
    total_system_reactive_power = float32(0x003C, unit="var")
    total_system_power_factor = float32(0x003E)
    frequency = float32(0x0046, unit="Hz")

    import_active_energy = float32(0x0048, unit="kWh")
    export_active_energy = float32(0x004A, unit="kWh")

    voltage_l1_l2 = float32(0x00C8, unit="V")
    voltage_l2_l3 = float32(0x00CA, unit="V")
    voltage_l3_l1 = float32(0x00CC, unit="V")
    average_voltage_ll = float32(0x00CE, unit="V")
    neutral_current = float32(0x00E0, unit="A")

    # Note 2 in the manual: total active energy is import + export.
    total_active_energy = float32(0x0156, unit="kWh")
    total_reactive_energy = float32(0x0158, unit="kvarh")

    resettable_total_active_energy = float32(0x0180, unit="kWh")
    resettable_import_active_energy = float32(0x0184, unit="kWh")
    resettable_export_active_energy = float32(0x0186, unit="kWh")
    # Import minus export, so unlike every other counter here it can fall.
    net_active_energy = float32(0x018C, unit="kWh")

    total_import_active_power = float32(0x0500, unit="W")
    total_export_active_power = float32(0x0502, unit="W")
