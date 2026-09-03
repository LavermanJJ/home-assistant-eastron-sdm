"""Model identity for the Eastron SDM meter family.

Nothing in this package imports Home Assistant: it is a self-contained device
library that talks to a ``modbus_connection.ModbusUnit`` and nothing else.
"""

from __future__ import annotations

from enum import StrEnum


class SdmModel(StrEnum):
    """A supported meter model.

    The value is stored verbatim in the config entry, so it must stay stable.
    """

    SDM120 = "SDM120"
    SDM630 = "SDM630"


#: Meter codes read from holding register ``0xFC02``, mapped to the model.
#:
#: ``0x0020`` for the SDM120 is documented in *SDM120-Modbus RTU Protocol*
#: (holding register 464515, "Meter code = 00 20"). The SDM630 code is **not**
#: in *SDM630 Modbus Protocol V1.8* — V2 hardware reports it, but the value
#: below is drawn from field reports rather than the datasheet. Detection is
#: therefore best-effort: an unrecognised code falls back to asking the user,
#: it never blocks setup. See ``docs/README.md`` for both documents.
METER_CODES: dict[int, SdmModel] = {
    0x0020: SdmModel.SDM120,
    0x0070: SdmModel.SDM630,
}

#: Values of the ``Network Parity Stop`` holding register (``0x0012``), which
#: encodes parity and stop bits together, as (parity, stopbits).
PARITY_STOP: dict[int, tuple[str, int]] = {
    0: ("N", 1),
    1: ("E", 1),
    2: ("O", 1),
    3: ("N", 2),
}

#: Values of the ``Network Baud Rate`` holding register (``0x001C``).
#:
#: Index 5 means 1200 baud on the SDM120 and is unused on the SDM630, which
#: tops out at 38400. Reading it back is informational only; this integration
#: never writes it.
BAUD_RATES: dict[int, int] = {
    0: 2400,
    1: 4800,
    2: 9600,
    3: 19200,
    4: 38400,
    5: 1200,
}
