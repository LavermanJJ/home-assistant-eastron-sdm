"""Holding-register components: who the meter is and how it is talking.

Split in two on purpose. The network settings block is documented for every
SDM model, while the ``0xFC00`` device-info block is not in the SDM630 V1.8
protocol document and older hardware answers it with an exception. Keeping
them apart lets a meter without device info still set up.
"""

from __future__ import annotations

from modbus_connection.model import Component, float32, raw_register, uint32


class SdmNetworkSettings(Component):
    """The meter's own view of its serial link, from holding registers (FC03).

    Read once at setup and surfaced as diagnostics. Useful when a meter has
    dropped off the bus: it tells you what the meter thinks its node address
    and line settings are, which is the first thing to check.
    """

    register_space = "holding"

    # SDM120 40019 / SDM630 40019. 0=8N1, 1=8E1, 2=8O1, 3=8N2.
    parity_stop = float32(0x0012)
    # SDM120 "Meter ID" 40021 / SDM630 "Network Node" 40021. 1..247.
    node_address = float32(0x0014)
    # SDM120 / SDM630 40029. Index into BAUD_RATES, not the baud rate itself.
    baud_rate = float32(0x001C)


class SdmDeviceInfo(Component):
    """Serial number, meter code and firmware version (holding, FC03).

    Documented at 464513/464515/464516 in the SDM120 protocol; the SDM630 V1.8
    document lists only the serial number. The three fields are contiguous, so
    they cost exactly one read of four registers -- an even start address and
    an even count, which the SDM firmware requires.
    """

    register_space = "holding"

    serial_number = uint32(0xFC00)
    meter_code = raw_register(0xFC02)
    software_version = raw_register(0xFC03)
