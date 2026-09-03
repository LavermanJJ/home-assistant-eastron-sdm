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

  `tests/test_sdm.py::test_every_block_read_is_legal` asserts all of this per
  model, against that model's own declared limit.
- The network settings block (`0x0012` parity/stop, `0x0014` node address,
  `0x001C` baud rate) is documented for **every** model above, which is what
  lets `SdmNetworkSettings` be model independent.
- Meter codes at `0xFC02` are documented for the SDM120 (`0x0020`), SDM630MCT
  (`0x0079`), SDM72D-M-1 (`0x0084`) and SDM72DM-V2 (`0x0089`). The SDM630 code
  is **not** documented — V1.8 lists only the serial number — and the value in
  `sdm/const.py` comes from field reports. The SDM120CT and SDM230 manuals
  document no meter code, so those two always reach the model-selection step.

## Known gaps

- **SDM630MCT `0x00FE`** is listed as "Total system power factor (1)" with the
  unit "Degrees". It cannot be both, and power factor is already at `0x003E`
  with phase angle at `0x0042`, so it is left unmapped rather than guessed.
- **SDM120 has no phase angle.** The SDM230 documents it at `0x0024` and the
  SDM630 at `0x0024`–`0x0028`, but the SDM120 document does not list it, so it
  is not declared for that model.
