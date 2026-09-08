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
#:
#: 0x1010 was reported by an SDM630 on software version 1.5, out of the same
#: four-register read that returned a correct serial number and firmware, and
#: that meter reads correctly on the SDM630 map: its line-to-line voltages are
#: the expected sqrt(3) multiple of its line-to-neutral ones, and its neutral
#: current is the vector sum of the two loaded phase currents. It is kept out
#: of ``METER_CODES`` for the same reason as 0x0004 -- one meter's word, and a
#: value nowhere near the 0x20-to-0x89 range every documented code occupies.
#:
#: Note this does not contradict a manual, because no manual documents the
#: SDM630's code either: 0x0070 in ``METER_CODES`` is itself a field report.
#: Two firmware generations now reporting values far outside the documented
#: range is the argument for preselecting rather than deciding -- whatever
#: 0xFC02 holds does not look stable across firmware revisions.
PROVISIONAL_METER_CODES: dict[int, SdmModel] = {
    0x0004: SdmModel.SDM120,
    0x1010: SdmModel.SDM630,
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

#: Models that are offered the reset button, and why each one is here.
#:
#: SDM630 -- documented. The register above is quoted from its own manual.
#:
#: SDM120 -- not documented, but **verified on hardware**. Its own
#: holding-register table stops at 0xFC03 and never mentions 0xF010, so this
#: rests on a measurement rather than on the manual. On software version 1.16
#: the write was accepted, and thirteen seconds later the next poll read:
#:
#:   maximum total / import system power demand  75.97 W -> 0.0
#:   maximum current demand                      0.3297 A -> 0.0
#:
#: while ``active_power`` carried on undisturbed and ``import_active_energy``
#: kept climbing across the reset without a step -- 0.028 to 0.033 kWh over
#: four minutes, which is the 75 W the power register was reading at the time.
#: The node address, baud rate and parity were re-read from the meter after
#: the press and were unchanged, which matters because those are 0xF010's
#: neighbours in the holding space.
#:
#: Note it also zeroes the *live* demand accumulators, not only their maxima,
#: so the demand period restarts. That follows from a maximum being derived
#: from the accumulator, and the SDM630 manual does not say it outright.
#:
#: The SDM120CT, SDM230, SDM630MCT and both SDM72D variants are absent for a
#: different reason again: nobody has read their documents. Move one up here
#: once someone has, not because the family probably shares the address.
DEMAND_RESET_MODELS: frozenset[SdmModel] = frozenset({SdmModel.SDM120, SdmModel.SDM630})

#: Minimum idle gap between two consecutive requests to the same meter, in
#: seconds.
#:
#: The SDM630 answers the first telegram of a poll and then starts dropping the
#: ones that follow it back to back. Measured over 15.6 h on a 9600-baud line
#: carrying one SDM630 and five SDM120, polling every 30 s: 354 failed polls,
#: 19% of that meter's, distributed over the poll's blocks as
#:
#:   0/58  60/48  200/60  260/10  334/48
#:      2    114      96      73      69
#:
#: The block that almost never fails is the only one always preceded by an idle
#: gap -- the poll's first read follows the scan interval, while the rest follow
#: their predecessor with no pause at all, since ``message_spacing`` defaults to
#: zero and the component reads its blocks in one loop.
#:
#: Every failure was a timeout: no CRC errors, no exception codes. That is what
#: rules out block size, the other suspect, and the five-block layout above is
#: the evidence -- the run was made with ``max_span`` lowered to 60 to test
#: exactly that, and the meter went on failing at the same rate. An over-long
#: request is documented to draw an exception response anyway, not silence, so
#: the ceiling stays at the 80 registers the SDM630 manual states.
#:
#: The five SDM120 on the same wire, same adapter, same baud rate read their
#: four blocks just as tightly -- and at 80 registers a larger frame than
#: anything the SDM630 asks for -- for three failures in ~8800 polls. So this is
#: not the line and not the adapter; it is how long this meter needs after
#: transmitting before it will take the next request addressed to it.
#:
#: Applied per unit, which is all the shared connection offers -- and that is
#: this fix's ceiling. The gap is measured from this meter's own last reply, so
#: it says nothing about the five other meters sharing the port. 50 ms costs the
#: SDM630 three gaps per poll and costs the others nothing.
#:
#: What that leaves: six clean hours, 753 consecutive polls, zero failures --
#: and then the six coordinators drifted into alignment and the meter settled at
#: ~6%. Reconstructing each poll's window from the debug log (start = finish -
#: duration) shows the collision directly, the gap between the other five
#: finishing and this one starting closing one cycle at a time:
#:
#:   +3.44s  +2.42s  +1.41s  +0.44s  overlap  overlap
#:       ok      ok      ok      ok     FAIL     FAIL
#:
#: Its first read now goes out while another meter is still on the wire, and is
#: missed exactly as a too-early read of its own was. The block failing most is
#: now 0/58, the poll's first: 27% of this meter's failures against 0.6% before.
#: And it self-perpetuates -- every meter on the port blocks behind the 10 s
#: timeout, so they all reschedule from the same instant and stay aligned.
#:
#: The fix for that is a connection-wide gap, which nothing in the chain
#: exposes: ``BaseModbusConnection`` takes ``message_spacing`` in its
#: constructor only, and ``modbus.async_get_unit()`` passes none. Home
#: Assistant's own YAML hub had the knob as ``message_wait_milliseconds``.
#:
#: A model missing here has not been measured, which is not the same as being
#: known to need no gap.
MESSAGE_SPACING: dict[SdmModel, float] = {SdmModel.SDM630: 0.05}
