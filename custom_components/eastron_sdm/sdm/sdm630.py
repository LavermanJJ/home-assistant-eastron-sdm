"""SDM630 input registers (FC04).

Transcribed from *Eastron SDM630 Modbus Smart Meter Modbus Protocol
Implementation V1.8*, section 1.2.1; see ``docs/README.md``. Every value is a
32-bit IEEE-754 float held in two consecutive registers, most significant
register first.

Addresses are Modbus protocol start addresses (the "Hi/Lo byte" column), not
the 3xxxx register numbers in the leftmost column.

The document marks per-phase parameters as invalid for some wiring systems
(3p3w in particular) with a cross rather than a tick; those read back as zero
instead of failing, so every field is declared unconditionally and it is the
installation that decides which ones mean anything.
"""

from __future__ import annotations

from modbus_connection.model import Component, float32


class Sdm630Measurements(Component):
    """Every documented SDM630 measurement.

    ``max_span`` caps a block at the 80 registers (40 float values) the meter
    will serve in one transaction -- section 1.2 is explicit that exceeding it
    draws an exception response.

    ``register_ranges`` mirrors the three parameter blocks the document
    defines: parameters 1-54, 101-135 and 168-191, which land on contiguous
    address runs. Reads may span freely inside a run and never cross between
    them, so the planner cannot wander into addresses the document does not
    describe. Together with ``max_span`` this settles at four reads per poll.
    """

    register_space = "input"
    max_span = 80
    register_ranges = (
        (0x0000, 0x006B),  # parameters 1-54
        (0x00C8, 0x010D),  # parameters 101-135
        (0x014E, 0x017D),  # parameters 168-191
    )

    # --- Per phase, line to neutral ---
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
    # Sign follows current direction: positive forward, negative reverse.
    power_factor_l1 = float32(0x001E)
    power_factor_l2 = float32(0x0020)
    power_factor_l3 = float32(0x0022)
    phase_angle_l1 = float32(0x0024, unit="°")
    phase_angle_l2 = float32(0x0026, unit="°")
    phase_angle_l3 = float32(0x0028, unit="°")

    # --- System totals and averages ---
    average_voltage_ln = float32(0x002A, unit="V")
    average_current = float32(0x002E, unit="A")
    sum_of_line_currents = float32(0x0030, unit="A")
    total_system_power = float32(0x0034, unit="W")
    total_system_apparent_power = float32(0x0038, unit="VA")
    total_system_reactive_power = float32(0x003C, unit="var")
    total_system_power_factor = float32(0x003E)
    total_system_phase_angle = float32(0x0042, unit="°")
    frequency = float32(0x0046, unit="Hz")

    # --- Energy ---
    import_active_energy = float32(0x0048, unit="kWh")
    export_active_energy = float32(0x004A, unit="kWh")
    import_reactive_energy = float32(0x004C, unit="kvarh")
    export_reactive_energy = float32(0x004E, unit="kvarh")
    total_apparent_energy = float32(0x0050, unit="kVAh")
    total_ampere_hours = float32(0x0052, unit="Ah")

    # --- Demand ---
    # Note 2 in the document: the power demand sum is computed as
    # import - export, so this is a net figure and may go negative.
    total_system_power_demand = float32(0x0054, unit="W")
    # The units column of the document says VA for parameter 44; it is the
    # maximum of parameter 43 and therefore watts. Treated as watts here.
    maximum_total_system_power_demand = float32(0x0056, unit="W")
    total_system_apparent_power_demand = float32(0x0064, unit="VA")
    maximum_total_system_apparent_power_demand = float32(0x0066, unit="VA")
    neutral_current_demand = float32(0x0068, unit="A")
    maximum_neutral_current_demand = float32(0x006A, unit="A")

    # --- Line to line ---
    voltage_l1_l2 = float32(0x00C8, unit="V")
    voltage_l2_l3 = float32(0x00CA, unit="V")
    voltage_l3_l1 = float32(0x00CC, unit="V")
    average_voltage_ll = float32(0x00CE, unit="V")
    neutral_current = float32(0x00E0, unit="A")

    # --- Total harmonic distortion ---
    voltage_thd_l1 = float32(0x00EA, unit="%")
    voltage_thd_l2 = float32(0x00EC, unit="%")
    voltage_thd_l3 = float32(0x00EE, unit="%")
    current_thd_l1 = float32(0x00F0, unit="%")
    current_thd_l2 = float32(0x00F2, unit="%")
    current_thd_l3 = float32(0x00F4, unit="%")
    average_voltage_thd_ln = float32(0x00F8, unit="%")
    average_current_thd = float32(0x00FA, unit="%")

    # --- Per-phase current demand ---
    current_demand_l1 = float32(0x0102, unit="A")
    current_demand_l2 = float32(0x0104, unit="A")
    current_demand_l3 = float32(0x0106, unit="A")
    maximum_current_demand_l1 = float32(0x0108, unit="A")
    maximum_current_demand_l2 = float32(0x010A, unit="A")
    maximum_current_demand_l3 = float32(0x010C, unit="A")

    # --- Line to line THD ---
    voltage_thd_l1_l2 = float32(0x014E, unit="%")
    voltage_thd_l2_l3 = float32(0x0150, unit="%")
    voltage_thd_l3_l1 = float32(0x0152, unit="%")
    average_voltage_thd_ll = float32(0x0154, unit="%")

    # --- Per-phase energy. Note 3: "total" is import + export. ---
    total_active_energy = float32(0x0156, unit="kWh")
    total_reactive_energy = float32(0x0158, unit="kvarh")
    import_active_energy_l1 = float32(0x015A, unit="kWh")
    import_active_energy_l2 = float32(0x015C, unit="kWh")
    import_active_energy_l3 = float32(0x015E, unit="kWh")
    export_active_energy_l1 = float32(0x0160, unit="kWh")
    export_active_energy_l2 = float32(0x0162, unit="kWh")
    export_active_energy_l3 = float32(0x0164, unit="kWh")
    total_active_energy_l1 = float32(0x0166, unit="kWh")
    total_active_energy_l2 = float32(0x0168, unit="kWh")
    total_active_energy_l3 = float32(0x016A, unit="kWh")
    import_reactive_energy_l1 = float32(0x016C, unit="kvarh")
    import_reactive_energy_l2 = float32(0x016E, unit="kvarh")
    import_reactive_energy_l3 = float32(0x0170, unit="kvarh")
    export_reactive_energy_l1 = float32(0x0172, unit="kvarh")
    export_reactive_energy_l2 = float32(0x0174, unit="kvarh")
    export_reactive_energy_l3 = float32(0x0176, unit="kvarh")
    total_reactive_energy_l1 = float32(0x0178, unit="kvarh")
    total_reactive_energy_l2 = float32(0x017A, unit="kvarh")
    total_reactive_energy_l3 = float32(0x017C, unit="kvarh")
