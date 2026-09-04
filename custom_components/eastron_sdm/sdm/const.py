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
#: A code in here configures a meter unattended, so it must be one the
#: hardware cannot contradict. Provisional codes belong in
#: ``PROVISIONAL_METER_CODES`` instead.
#:
#: Detection is best-effort throughout: an unrecognised or missing code falls
#: back to asking the user, it never blocks setup.
METER_CODES: dict[int, SdmModel] = {
    0x0020: SdmModel.SDM120,
    0x0070: SdmModel.SDM630,
    0x0079: SdmModel.SDM630MCT,
    0x0084: SdmModel.SDM72D_M_1,
    0x0089: SdmModel.SDM72DM_V2,
}

#: Codes seen in the field that name a model without proving it. They
#: preselect on the model step; they never decide on their own.
#:
#: 0x0004 was reported by an SDM120 on software version 1.16, out of the same
#: four-register read that returned a correct serial number and firmware, and
#: that meter reads correctly on the SDM120 map. It is kept out of
#: ``METER_CODES`` because a documented code is a promise the manual makes and
#: this is one meter's word: it sits far below the 0x20-and-above range every
#: documented code occupies, which is a hint that whatever populates it here is
#: not the field the manual describes.
#:
#: The models that could collide are exactly the ones that cannot be ruled out.
#: The SDM120CT would be harmless -- it shares the SDM120 register map -- but
#: the SDM230 does not, and the SDM230 and SDM120CT are precisely the two
#: models whose manuals document no meter code at all, so nothing says what
#: their 0xFC02 holds. Auto-configuring on 0x0004 would put an SDM230 on the
#: SDM120 map, reading every value from the wrong address into a plausible
#: number, and would raise a permanent mismatch repair issue against an SDM230
#: entry its owner had set up correctly by hand.
#:
#: Preselecting costs that user one confirmation and can be wrong out loud.
PROVISIONAL_METER_CODES: dict[int, SdmModel] = {
    0x0004: SdmModel.SDM120,
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

#: Holding register that clears the maximum-demand readings, and the value
#: that does it. SDM630 Modbus Protocol V1.8, quoted verbatim:
#:   461457 30729 Reset F0 10 | "00 00: reset the Maximum demand"
#:                            | Length: 2 byte, Data Format: Hex, wo
#:
#: Written with function code 16, which is what "Function code 10 to set
#: holding parameter" names in the same documents. The note there about even
#: start addresses and even register counts is about *floating point*
#: parameters, which span two registers; this one is a single 2-byte Hex
#: register, so a count of one is what it takes.
DEMAND_RESET_REGISTER: int = 0xF010
DEMAND_RESET_VALUE: int = 0x0000

#: Models whose protocol document describes that register.
#:
#: The SDM630 document is the only one here that does. The SDM120's holding
#: register table stops at 0xFC03 and never mentions 0xF010 -- so a reset is
#: deliberately not offered on the SDM120, rather than offered as an
#: undocumented write to a meter that may be billing someone. The SDM120CT,
#: SDM230, SDM630MCT and both SDM72D variants are absent for a weaker reason:
#: their documents are not in ``docs/`` to check. Add a model here once its
#: document has been read, not because the family probably shares the address.
DEMAND_RESET_MODELS: frozenset[SdmModel] = frozenset({SdmModel.SDM630})
