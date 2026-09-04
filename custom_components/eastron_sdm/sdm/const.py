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
    SDM120CT = "SDM120CT"
    SDM230 = "SDM230"
    SDM630 = "SDM630"
    SDM630MCT = "SDM630MCT"
    # Both of these are sold as "SDM72D" and they are not interchangeable, so
    # neither gets the bare family name: on the model-selection step the value
    # is the label, and "SDM72D" next to "SDM72DM-V2" invites a V2 owner to
    # pick the energy-only map and lose voltage, current and power factor.
    SDM72D_M_1 = "SDM72D-M-1"
    SDM72DM_V2 = "SDM72DM-V2"


#: Meter codes read from holding register ``0xFC02``, mapped to the model.
#:
#: Documented in the corresponding protocol manual, quoted verbatim:
#:   0x0020  "Meter code = 00 20"      SDM120-Modbus RTU Protocol
#:   0x0079  "Meter code = 00 79"      SDM630MCT Modbus Protocol V1.7
#:   0x0084  "SDM72D-M-1= 00 84"       SDM72D-M-1 User Manual V1.4
#:   0x0089  "SDM72D-M = 00 89"        SDM72DM-V2 User Manual V1.1
#:
#: The SDM630 code is **not** documented -- SDM630 Modbus Protocol V1.8 lists
#: only the serial number at 0xFC00 -- and 0x0070 comes from field reports.
#: The SDM120CT and SDM230 manuals document no meter code at all, so those two
#: are never detected and always reach the model step.
#:
#: 0x0004 is a field report too, from an SDM120 running software version 1.16
#: that reports it where its own manual promises 0x0020. It is mapped despite
#: sitting far below every documented code -- all of which are 0x20 or above --
#: because leaving it out costs that meter automatic detection, while getting
#: it wrong costs at most the model *name*: SDM120 and SDM120CT share one
#: register map, and the CT documents no code of its own. A report of 0x0004
#: from outside the SDM120 family is the one thing that would make this entry
#: wrong, which is why its provenance is recorded here.
#:
#: One model may therefore appear under more than one code. The reverse must
#: never happen: a code resolving to two models would make detection a guess.
#:
#: Detection is best-effort throughout: an unrecognised or missing code falls
#: back to asking the user, it never blocks setup.
METER_CODES: dict[int, SdmModel] = {
    0x0004: SdmModel.SDM120,
    0x0020: SdmModel.SDM120,
    0x0070: SdmModel.SDM630,
    0x0079: SdmModel.SDM630MCT,
    0x0084: SdmModel.SDM72D_M_1,
    0x0089: SdmModel.SDM72DM_V2,
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
#: Index 5 means 1200 baud on the SDM120; the SDM72D range reaches 1200 too,
#: while the SDM630 tops out at 38400. Reading it back is informational only;
#: this integration never writes it.
BAUD_RATES: dict[int, int] = {
    0: 2400,
    1: 4800,
    2: 9600,
    3: 19200,
    4: 38400,
    5: 1200,
}
