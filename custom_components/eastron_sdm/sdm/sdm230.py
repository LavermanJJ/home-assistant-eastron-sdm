"""SDM230 input registers (FC04).

Transcribed from *Eastron SDM230Modbus Smart Meter Modbus Protocol
Implementation*, the input register table in section 1.2; see
``docs/README.md``. Values are 32-bit IEEE-754 floats over two registers,
most significant register first.

The SDM230 map is the SDM120 map plus the phase angle at 0x0024, so the
component says exactly that rather than restating twenty-one addresses. The
document names three of the demand parameters differently -- "current system
positive power demand" for what the SDM120 calls import system power demand --
but they are the same addresses measuring the same thing, so the field names
are shared.
"""

from __future__ import annotations

from modbus_connection.model import float32

from .sdm120 import Sdm120Measurements


class Sdm230Measurements(Sdm120Measurements):
    """Every documented SDM230 measurement.

    Same 80-register transaction limit as the SDM120: "The SDM230 can transfer
    a maximum of 40 values in a single transaction; therefore the maximum
    number of registers requestable is 80."
    """

    phase_angle = float32(0x0024, unit="°")
