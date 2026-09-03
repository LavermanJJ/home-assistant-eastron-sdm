"""SDM630MCT input registers (FC04).

Transcribed from *Eastron SDM630MCT Smart Meter Modbus Protocol
Implementation V1.7*; see ``docs/README.md``.

The MCT map is the SDM630 map plus reactive power demand and a block of
resettable energy counters, so the component states the delta rather than
restating ninety addresses.
"""

from __future__ import annotations

from modbus_connection.model import float32

from .sdm630 import Sdm630Measurements


class Sdm630MctMeasurements(Sdm630Measurements):
    """Every documented SDM630MCT measurement.

    ``max_span`` drops to 60 registers. The document contradicts itself --
    section 1.1 says "a maximum of 30 values in a single transaction;
    therefore the maximum number of registers requestable is 60", while
    section 1.2 repeats the SDM630's "restricted to 40 parameters or less".
    The smaller limit is the safe reading: a request the meter refuses costs
    every field in that block.

    One documented parameter is deliberately left out. Address 0x00FE is
    listed as "Total system power factor (1)" with the unit "Degrees", which
    cannot be both, and the SDM630 map already has power factor at 0x003E and
    phase angle at 0x0042. Guessing which one it is would put a plausible
    wrong number on a dashboard, so it stays unmapped until hardware settles
    it.
    """

    max_span = 60
    register_ranges = (
        (0x0000, 0x006F),  # SDM630 block, extended by reactive power demand
        (0x00C8, 0x010D),
        (0x014E, 0x018B),  # extended by the resettable energy counters
    )

    total_system_reactive_power_demand = float32(0x006C, unit="var")
    maximum_total_system_reactive_power_demand = float32(0x006E, unit="var")

    # Counters the user can zero from the meter, tracked alongside the
    # lifetime totals the SDM630 already exposes.
    resettable_total_active_energy = float32(0x0180, unit="kWh")
    resettable_total_reactive_energy = float32(0x0182, unit="kvarh")
    resettable_import_active_energy = float32(0x0184, unit="kWh")
    resettable_export_active_energy = float32(0x0186, unit="kWh")
    resettable_import_reactive_energy = float32(0x0188, unit="kvarh")
    resettable_export_reactive_energy = float32(0x018A, unit="kvarh")
