# Protocol sources

The register maps in `custom_components/eastron_sdm/sdm/` are transcribed from
the manufacturer's protocol documents. They are not redistributed here — fetch
them and drop them in this directory when working on the maps.

| Model | Document | Source |
|---|---|---|
| SDM120 | SDM120-Modbus RTU Protocol — register map pp. 5–8 | [eastroneurope.com](https://www.eastroneurope.com/images/uploads/products/protocol/SDM120-MODBUS_Protocol.pdf) |
| SDM120CT | SDM120CT Modbus protocol | [eastroneurope.com](https://www.eastroneurope.com/images/uploads/products/protocol/SDM120CT_Modbus_protocol.pdf) |
| SDM230 | SDM230Modbus Modbus Protocol Implementation | [innon.com mirror](https://downloads.innon.com/hubfs/downloads.innon.com/Power%20Meters/SDM230-MOD-MID/Manuals/SDM230-PROTOCOL.pdf) |
| SDM630 | SDM630 Modbus Protocol Implementation **V1.8** — §1.2.1 input, §1.3.1 holding | [eastroneurope.com](https://www.eastroneurope.com/images/uploads/products/protocol/SDM630_MODBUS_Protocol.pdf) |
| SDM630MCT | SDM630MCT Modbus Protocol Implementation **V1.7** | [eastroneurope.com](https://www.eastroneurope.com/images/uploads/products/protocol/SDM630MCT_MODBUS_Protocol_V1.7.pdf) |
| SDM72D | SDM72D-M-1 User Manual **V1.4** | [eastrongroup.com](https://www.eastrongroup.com/eastrongroup/2024/08/21/eastronsdm72d-m-1usermanualv1.4.pdf) |
| SDM72DM-V2 | SDM72DM-V2 User Manual **V1.1** | B+G e-tech (Eastron Germany) |

Eastron gates most protocol PDFs behind registration on the product pages; the
links above are the ones served directly.

## Facts the maps depend on

- Every parameter is a 32-bit IEEE-754 float in two consecutive registers,
  **most significant register first**. The SDM630 can be switched to reversed
  order through its Register Order holding register; this integration assumes
  the default.
- Measurements live in the input register space, read with **function code
  04**. Settings and identity live in holding registers, function code 03.
- A request's start address and register count must both be **even**.
- The per-request ceiling is **not the same across the range**:

  | Limit | Models | Quote |
  |---|---|---|
  | 40 values / 80 registers | SDM120, SDM120CT, SDM230, SDM630 | "maximum of 40 values in a single transaction; therefore the maximum number of registers requestable is 80" |
  | 30 values / 60 registers | SDM72D, SDM72DM-V2, SDM630MCT | "Each request for data must be restricted to 30 parameters or less" |

  The SDM630MCT document contradicts itself, giving 30 values / 60 registers in
  §1.1 and repeating the SDM630's "40 parameters" in §1.2. The integration
  takes the smaller figure: a rejected request costs every field in the block.

  Two tests hold this. `test_max_span_matches_the_protocol_document` pins each
  model's declared `max_span` against the figure in its manual — the table in
  the test is duplicated from the documents on purpose, because asserting that
  a read fits inside `max_span` only proves the planner honours the number it
  was given. `test_every_block_read_is_legal` then checks the even start
  address, the even count, and that no block exceeds that model's limit.
- The network settings block (`0x0012` parity/stop, `0x0014` node address,
  `0x001C` baud rate) is documented for **every** model above, which is what
  lets `SdmNetworkSettings` be model independent.
- Meter codes at `0xFC02` are documented for the SDM120 (`0x0020`), SDM630MCT
  (`0x0079`), SDM72D-M-1 (`0x0084`) and SDM72DM-V2 (`0x0089`). The SDM630 code
  is **not** documented — V1.8 lists only the serial number — and the value in
  `sdm/const.py` comes from field reports. The SDM120CT and SDM230 manuals
  document no meter code, so those two always reach the model-selection step.
- **Not every SDM120 reports `0x0020`.** One running software version 1.16 was
  observed reporting `0x0004`, out of the same four-register block that
  returned a correct serial number and firmware version, and it reads correctly
  on the SDM120 map. It sits well below the `0x20`-and-above range every
  documented code occupies, which is a hint that whatever populates it there is
  not the field the manual describes.

  It therefore lives in `PROVISIONAL_METER_CODES`, not `METER_CODES`: it
  preselects the SDM120 on the model step and never configures a meter on its
  own. A code in `METER_CODES` skips that step entirely, which is only safe for
  a code the hardware cannot contradict. The SDM230 is why — it does not share
  the SDM120 register map, and it is one of the two models whose manual
  documents no meter code at all, so nothing says what its `0xFC02` holds.
  Auto-configuring on `0x0004` would put an SDM230 on the SDM120 map and raise
  a permanent mismatch repair issue against an entry set up correctly by hand.

  Promote it to `METER_CODES` only once a second, independent report confirms
  it, and only if no model outside the SDM120 family has been seen reporting
  it.

- **The maximum-demand reset lives at `0xF010`.** SDM630 Modbus Protocol V1.8
  documents it as `461457 / 30729 Reset F0 10`, write-only, 2-byte Hex, where
  `00 00` resets the maximum demand. Written with function code 16 — "Function
  code 10 to set holding parameter" in these documents is FC16, and the note
  about even start addresses and even register counts applies to floating-point
  parameters spanning two registers, not to a single Hex register.

  **The SDM120 does not document it but does implement it**, verified on
  software version 1.16: the write was accepted and the next poll read the
  maxima as zero, while `active_power` was undisturbed and
  `import_active_energy` carried on across the reset with no step. The node
  address, baud rate and parity were re-read afterwards and unchanged — worth
  checking on any model added here, since those are `0xF010`'s neighbours.

  The reset also zeroes the *live* demand accumulators, not just their maxima,
  so the demand period restarts. The SDM630 manual does not say so outright.

  The SDM120CT, SDM230, SDM630MCT and both SDM72D variants are not offered a
  reset, purely because nobody has read their documents.

## Reading across undocumented addresses

Declaring a `register_ranges` entry tells the planner it may merge reads across
everything inside it, `max_span` permitting — including addresses between the
documented parameters. That is usually what you want: the SDM family shares one
firmware map, the holes are the same registers other models populate, and
merging is what keeps a poll to a handful of round trips.

It stops being reasonable when a range is mostly hole. The SDM72D-M-1 declares
four parameters between `0x000C` and `0x0035`; a single range there produced one
42-register read spanning `0x0012`–`0x0033`, which that meter's manual does not
describe at all. An illegal-data-address answer to any of them fails the whole
block, so all twelve of its entities would have gone unavailable every poll,
including the ones that read fine. Its ranges are now tight around the fields:
one extra round trip, and 26 registers on the wire instead of 60.

## Known gaps

- **SDM630MCT `0x00FE`** is listed as "Total system power factor (1)" with the
  unit "Degrees". It cannot be both, and power factor is already at `0x003E`
  with phase angle at `0x0042`, so it is left unmapped rather than guessed.
- **SDM120 has no phase angle.** The SDM230 documents it at `0x0024` and the
  SDM630 at `0x0024`–`0x0028`, but the SDM120 document does not list it, so it
  is not declared for that model.
