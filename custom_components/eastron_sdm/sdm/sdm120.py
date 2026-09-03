"""SDM120 input registers (FC04).

Transcribed from *SDM120-Modbus RTU Protocol* (Zhejiang Eastron), the register
map on pages 5-6; see ``docs/README.md``. Every value
is a 32-bit IEEE-754 float held in two consecutive registers, most significant
register first -- which is ``float32``'s ``word_order="big"`` default.

Addresses here are Modbus protocol start addresses (the "Hi/Lo byte" column),
not the 3xxxx register numbers in the leftmost column.
"""

from __future__ import annotations

from modbus_connection.model import Component, float32


class Sdm120Measurements(Component):
    """Every documented SDM120 measurement.

    ``max_span`` caps a block at the 80 registers (40 float values) the meter
    will serve in one transaction; exceeding it draws an exception response.
    ``register_ranges`` bounds the planner to the address runs the SDM family
    map defines, so a merged block can never wander past them. Together they
    settle at four reads per poll, over-reading only the small holes between
    documented parameters inside each run.
    """

    register_space = "input"
    max_span = 80
    register_ranges = (
        (0x0000, 0x005F),
        (0x0102, 0x0109),
        (0x0156, 0x0159),
    )

    voltage = float32(0x0000, unit="V")
    current = float32(0x0006, unit="A")
    active_power = float32(0x000C, unit="W")
    apparent_power = float32(0x0012, unit="VA")
    reactive_power = float32(0x0018, unit="var")
    power_factor = float32(0x001E)

    frequency = float32(0x0046, unit="Hz")
    import_active_energy = float32(0x0048, unit="kWh")
    export_active_energy = float32(0x004A, unit="kWh")
    import_reactive_energy = float32(0x004C, unit="kvarh")
    export_reactive_energy = float32(0x004E, unit="kvarh")

    total_system_power_demand = float32(0x0054, unit="W")
    maximum_total_system_power_demand = float32(0x0056, unit="W")
    import_system_power_demand = float32(0x0058, unit="W")
    maximum_import_system_power_demand = float32(0x005A, unit="W")
    export_system_power_demand = float32(0x005C, unit="W")
    maximum_export_system_power_demand = float32(0x005E, unit="W")

    current_demand = float32(0x0102, unit="A")
    maximum_current_demand = float32(0x0108, unit="A")

    # Note 3 on the SDM630 sheet applies here too: "total" is import + export
    # by default, but the SDM120 "Measurement mode" register (0xF920) can make
    # it import only, or import - export. Read the meter's mode before trusting
    # this as a net figure.
    total_active_energy = float32(0x0156, unit="kWh")
    total_reactive_energy = float32(0x0158, unit="kvarh")
