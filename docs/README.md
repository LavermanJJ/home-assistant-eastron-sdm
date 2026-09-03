# Protocol sources

The register maps in `custom_components/eastron_sdm/sdm/` are transcribed from
the manufacturer's protocol documents. They are not redistributed here — fetch
them from Eastron and drop them in this directory when working on the maps:

| Model | Document | URL |
|---|---|---|
| SDM630 | Eastron SDM630 Modbus Smart Meter Modbus Protocol Implementation **V1.8** — section 1.2.1 (input registers), 1.3.1 (holding registers) | <https://www.eastroneurope.com/images/uploads/products/protocol/SDM630_MODBUS_Protocol.pdf> |
| SDM120 | SDM120-Modbus RTU Protocol — register map on pages 5–8 | <https://www.eastroneurope.com/images/uploads/products/protocol/SDM120-MODBUS_Protocol.pdf> |

```bash
curl -O https://www.eastroneurope.com/images/uploads/products/protocol/SDM630_MODBUS_Protocol.pdf
curl -O https://www.eastroneurope.com/images/uploads/products/protocol/SDM120-MODBUS_Protocol.pdf
```

## Facts the maps depend on

- Every parameter is a 32-bit IEEE-754 float in two consecutive registers,
  **most significant register first**. The SDM630 can be switched to reversed
  order through its Register Order holding register; this integration assumes
  the default.
- Measurements live in the input register space, read with **function code 04**.
  Settings and identity live in holding registers, function code 03.
- A request's start address and register count must both be **even**, and a
  single request may not exceed **80 registers** (40 float values). All three
  are asserted in `tests/test_sdm.py::test_every_block_read_is_legal`.
- The SDM630 V1.8 document describes only the serial number at `0xFC00`. Meter
  code (`0xFC02`) and software version (`0xFC03`) are documented for the
  SDM120; the SDM630 code in `sdm/const.py` comes from field reports, which is
  why an unrecognised code asks the user rather than failing.
