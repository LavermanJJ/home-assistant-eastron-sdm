# Eastron SDM for Home Assistant

A Home Assistant integration for Eastron SDM energy meters over Modbus, built on
Home Assistant's shared Modbus connection manager.

Works over an RS485 serial port or over TCP (a serial gateway such as ser2net,
or a meter that speaks Modbus TCP natively).

| Model | Phases | Entities | Per-request limit | Auto-detected |
|---|---|---|---|---|
| SDM120 | 1 | 21 | 80 registers | yes (`0x0020`) |
| SDM120CT | 1 | 21 | 80 registers | no — pick the model |
| SDM230 | 1 | 22 | 80 registers | no — pick the model |
| SDM630 | 3 | 85 | 80 registers | yes (`0x0070`, unofficial) |
| SDM630MCT | 3 | 93 | 60 registers | yes (`0x0079`) |
| SDM72D-M-1 | 3 | 12 | 60 registers | yes (`0x0084`) |
| SDM72DM-V2 | 3 | 41 | 60 registers | yes (`0x0089`) |

Meters whose manual documents no meter code, or whose code this integration
does not recognise, are not a failure case: setup asks which model it is.

The two meters sold as SDM72D are **not interchangeable** — the -M-1 is an
energy meter with no voltage or current registers at all, while the V2
measures the full three-phase set. They report different meter codes, so
detection tells them apart.

## Why one device per meter

A USB-RS485 converter is not a device and not a hub — it is a path. A serial bus
is a single exclusive resource: only one party can talk on it at a time.

Since the 2026 Modbus modernization, Home Assistant's `modbus` integration owns a
shared connection manager. This integration hands it the connection parameters
and a unit ID and gets back a unit; every entry addressing the same port shares
one connection, with requests serialized behind its lock. The connection opens
when the first meter needs it and closes when the last entry unloads.

So six meters on one converter are **six config entries and six devices sharing
one connection** — not six hubs each opening the same port.

```
config entries                     shared connection
  SDM630-M   unit 1  ─┐
  SDM120 #1  unit 2  ─┤
  SDM120 #2  unit 3  ─┼──▶  /dev/ttyUSB0  ──▶  RS485 bus
  SDM120 #3  unit 4  ─┤     (one port, one lock,
  SDM120 #4  unit 5  ─┤      requests serialized)
  SDM120 #5  unit 6  ─┘
```

## Installation

**HACS** — add this repository as a custom repository of type *Integration*,
install it, and restart Home Assistant.

Requires **Home Assistant 2026.9.0 or newer**: the shared Modbus connection
manager this is built on (`modbus.async_get_unit`) landed in that release.

**Manual** — copy `custom_components/eastron_sdm` into your Home Assistant
`config/custom_components/` directory and restart.

## Setup

*Settings → Devices & services → Add integration → Eastron SDM.*

Choose **RS485 serial port** or **TCP**, then give the meter's link settings and
its unit ID. The integration reads the meter's identity block to work out the
model and serial number; if the meter reports a code it does not recognise, it
asks you which model it is rather than refusing.

Adding the rest of the meters on the same bus is quick: the form is prefilled
from the last meter you configured the same way, so only the unit ID changes.

**Every meter on one RS485 bus must share a baud rate, parity and stop bits.**
That is a property of the wiring, not of Home Assistant. If you try to add a
meter on a port that is already open with different line settings, setup says so
instead of quietly opening a second, conflicting connection.

Each meter's own settings are readable from its front panel under the Modbus
menu — and after setup, from the Node address and Line settings diagnostic
sensors.

## Energy dashboard

Import and export active energy carry `device_class: energy`, kWh, and
`state_class: total_increasing`, so they appear directly as grid consumption and
return sources. `total_increasing` also means a meter reset reads as a new cycle
rather than as a large negative reading.

Note that on the SDM120 the meaning of *total* active energy depends on the
meter's own measurement-mode register: import only, import + export (the
default), or import − export. Import and export are unambiguous; prefer them.

## Entities

Every model exposes its full documented register map. Common measurements —
voltages, currents, powers, power factor, frequency and the import/export/total
energy counters — are enabled by default. Harmonics, demand figures, phase
angles and per-phase energy are registered but disabled, so they are one click
away without crowding the device page.

Disabled entities are still read: they share a block read with their neighbours,
so hiding them costs nothing on the bus.

## Polling

Each meter polls in four block reads. The default scan interval is 30 seconds
and the floor is 10. Because meters on one port queue behind each other on a
single connection, the useful interval depends on how many meters share the bus
and at what baud rate — a short interval across many meters at 2400 baud will
saturate it. Adjust under the integration's *Configure* option.

If a meter rejects a block read with an illegal-data-address exception, its
model class in `custom_components/eastron_sdm/sdm/` carries `register_ranges`
and `max_span` to cut the planner back to what that unit answers.

## Register maps

Transcribed from the manufacturer's protocol documents. See
[`docs/README.md`](docs/README.md) for the exact document versions, the sections
used, and the protocol facts the maps depend on.

- [SDM630 Modbus Protocol V1.8](https://www.eastroneurope.com/images/uploads/products/protocol/SDM630_MODBUS_Protocol.pdf)
- [SDM120-Modbus RTU Protocol](https://www.eastroneurope.com/images/uploads/products/protocol/SDM120-MODBUS_Protocol.pdf)

Every measurement is a 32-bit IEEE-754 float in two consecutive input registers,
most significant register first, read with function code 04. Requests must use
an even start address and an even register count, and may not exceed 80
registers; the tests assert all three.

## Branding

The Eastron mark in `custom_components/eastron_sdm/brand/` is served by Home
Assistant's local brand API, which resolves images by integration **domain**.
The brands repository does carry an `eastron` entry, but that belongs to the
core virtual integration of that name (which redirects to HomeWizard), and
`eastron_sdm` is a different domain -- so the assets have to travel with this
repository. Since Home Assistant 2026.3 that is the supported way for a custom
integration to brand itself, and local images take priority over the CDN.

This integration is not affiliated with or endorsed by Eastron.

## Architecture

```
custom_components/eastron_sdm/
├── sdm/          the device library: register maps and the meter object.
│                 Imports no Home Assistant, so it can be lifted into its own
│                 PyPI package unchanged if this ever goes to core.
├── connection.py config entry data -> Modbus connection parameters
├── config_flow.py
├── coordinator.py
└── sensor.py     one description table, filtered by what the model declares
```

The `sdm/` package is built on
[`modbus-connection`](https://github.com/home-assistant-libs/modbus-connection),
which does the framing, decoding and read planning. That is why the register
maps are declarative: an address, a type, a unit.

## Adding a model

1. Add a module under `sdm/` with a `Component` subclass declaring the model's
   input registers, transcribed from its protocol document, and set `max_span`
   to that document's per-request limit. If the map is another model's plus a
   few registers, subclass that model's component and declare only the
   difference — as `sdm230.py` and `sdm630mct.py` do.
2. Add the model to `SdmModel` and to `MEASUREMENTS` in `sdm/meter.py`, and its
   meter code to `METER_CODES` in `sdm/const.py`.
3. Add any new field names to `SENSORS` in `sensor.py` and to `strings.json`.
4. Record the document and its version in `docs/README.md`.

`test_every_model_field_becomes_a_sensor` fails if step 3 is forgotten.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install --group dev
.venv/bin/pytest tests
.venv/bin/ruff check custom_components tests
.venv/bin/mypy custom_components/eastron_sdm
```

Tests run against an in-memory Modbus unit from `modbus-connection`, so the
register model is exercised through real decoding rather than mocks.

## Status

Verified against the protocol documents and the test suite. Not yet verified
against physical hardware — when first connecting a real meter, compare
voltage, current, active power and total energy against the meter's own display
before trusting the readings. A wrong word order or a one-register slip decodes
to a plausible number rather than to an error.

Measured against Home Assistant's [integration quality
scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/),
this reaches platinum on the platinum rules themselves but not on the tiers
below it: seven rules are still open, tracked with a reason each in
[`custom_components/eastron_sdm/quality_scale.yaml`](custom_components/eastron_sdm/quality_scale.yaml).

## Licence

Apache License 2.0. See [LICENSE](LICENSE).
