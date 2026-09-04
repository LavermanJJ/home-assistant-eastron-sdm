<p align="center">
  <a href="https://github.com/lavermanjj/home-assistant-eastron-sdm">
    <img src="https://raw.githubusercontent.com/LavermanJJ/home-assistant-eastron-sdm/main/custom_components/eastron_sdm/brand/logo%402x.png" alt="Eastron SDM" height="80">
  </a>
</p>

<h3 align="center">Home Assistant Eastron SDM integration</h3>

A Home Assistant integration for Eastron SDM energy meters over Modbus, built on
Home Assistant's shared Modbus connection manager. It is not affiliated, associated, authorized, endorsed by, or in any way officially connected with the [Eastron Europe Limited](https://www.eastroneurope.com/about).

Works over an RS485 serial port or over TCP (a serial gateway such as ser2net,
or a meter that speaks Modbus TCP natively).

| Model | Phases | Entities | Per-request limit | Auto-detected |
|---|---|---|---|---|
| SDM120 | 1 | 21 | 80 registers | yes (`0x0020`); `0x0004` preselects |
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

*Reconfigure*, on an existing meter, changes its link settings or unit ID. It
re-reads the identity block on the way through, so a meter that contradicts the
model the entry is set to gets that raised there — with the reported model
preselected — instead of being left to read the wrong registers.

Adding the rest of the meters on the same bus is quick: the form is prefilled
from the last meter you configured the same way, so only the unit ID changes.

**Every meter on one RS485 bus must share a baud rate, parity and stop bits.**
That is a property of the wiring, not of Home Assistant. If you try to add a
meter on a port that is already open with different line settings, setup says so
instead of quietly opening a second, conflicting connection.

Each meter's own settings are readable from its front panel under the Modbus
menu — and after setup, from the Node address and Line settings diagnostic
sensors.

## Removing a meter

*Settings → Devices & services → Eastron SDM → the meter's ⋮ menu → Delete.*

Each meter is its own config entry, so deleting one leaves the rest of the bus
running. The connection is shared and reference-counted: the port stays open
until the **last** entry using it goes, and is closed and released only then.

Deleting takes the device, its entities and their recorded history with it. To
stop polling a meter without losing its statistics, choose *Disable* from the
same menu instead — that releases its claim on the connection and leaves the
history intact.

To remove the integration itself, delete every meter first, then uninstall it
in HACS (or delete `config/custom_components/eastron_sdm/`) and restart. Home
Assistant closes the shared connection when the last entry unloads, so nothing
is left holding the serial port.


## Energy dashboard

Import and export active energy carry `device_class: energy`, kWh, and
`state_class: total_increasing`, so they appear directly as grid consumption and
return sources. `total_increasing` also means a meter reset reads as a new cycle
rather than as a large negative reading.

Note that on the SDM120 the meaning of *total* active energy depends on the
meter's own measurement-mode register: import only, import + export (the
default), or import − export. Import and export are unambiguous; prefer them.

## Automation examples

Entity IDs follow the entry title, so a meter named *SDM630 (1)* gives
`sensor.sdm630_1_voltage_l1`. Adjust the names below to match yours.

Warn when a phase sags — a loose neutral or an overloaded leg shows up here
long before anything trips:

```yaml
automation:
  - alias: Phase voltage low
    triggers:
      - trigger: numeric_state
        entity_id:
          - sensor.sdm630_1_voltage_l1
          - sensor.sdm630_1_voltage_l2
          - sensor.sdm630_1_voltage_l3
        below: 210
        for: "00:01:00"
    actions:
      - action: notify.persistent_notification
        data:
          message: "{{ trigger.to_state.name }} is {{ trigger.to_state.state }} V"
```

Track how unbalanced the three phases are, which is what actually heats up a
neutral conductor:

```yaml
template:
  - sensor:
      - name: Phase imbalance
        unit_of_measurement: "%"
        state_class: measurement
        state: >
          {% set p = [
            states('sensor.sdm630_1_active_power_l1') | float(0),
            states('sensor.sdm630_1_active_power_l2') | float(0),
            states('sensor.sdm630_1_active_power_l3') | float(0),
          ] %}
          {% set avg = (p | sum) / 3 %}
          {{ 0 if avg == 0 else
             ((p | max) - (p | min)) / avg * 100 | round(1) }}
```

Split one meter's lifetime counter into daily and monthly figures, without
touching the meter's own resettable registers:

```yaml
utility_meter:
  heat_pump_daily:
    source: sensor.sdm120_2_import_active_energy
    cycle: daily
  heat_pump_monthly:
    source: sensor.sdm120_2_import_active_energy
    cycle: monthly
```


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

## Troubleshooting

**"No answer from that unit ID."** Work down this list in order — each step
rules out the ones below it.

1. **A/B polarity.** By far the commonest fault, and it looks exactly like a
   dead meter. Swap the two data lines and try again; RS485 is differential
   and nothing is harmed by having had them the wrong way round.
2. **The meter's own address.** Read it off the front panel under the Modbus
   menu. The factory default is 1, so two meters straight out of the box both
   answer to 1 and collide — give each its own address before wiring the
   second one on.
3. **Line settings.** Baud rate, parity and stop bits have to match what the
   meter is set to. The SDM630 leaves the factory at 9600 8N1.
4. **Termination and stub length.** A long run with no 120 Ω resistor at each
   end, or a short one with both fitted, tends to show up as reads that
   sometimes work rather than as a clean failure.

**"That port is already in use with different line settings."** Another entry
holds the port at a different baud rate or parity. Every meter on one bus must
agree, so one of the two entries is wrong: check both meters' front panels and
*Reconfigure* whichever is misdescribed. The flow releases the entry's own
connection before probing, so changing a baud rate does not conflict with
itself.

**A repair issue says the model may be wrong.** The meter reports a model code
whose register map is not the one configured, so every value is being read from
the wrong address — and a wrong address decodes to a plausible number, not to
an error. Run *Reconfigure* on that meter: the flow notices the contradiction
and offers the model the meter reports, preselected, for you to confirm. It is
offered rather than applied, because the SDM630's meter code is a field report
rather than a documented one — so if you are sure the configured model is right
and the reported code is not, keep it and the issue can be ignored.

**Readings look plausible but wrong.** Compare voltage, current, active power
and total energy against the meter's own display. A one-register slip or a
reversed word order decodes to a believable number, so only the display settles
it. If they disagree, the diagnostics download (device page → ⋮ → *Download
diagnostics*) has the raw decoded values and belongs in the bug report.

**Entities drop to unavailable now and then.** The bus is probably saturated:
every meter on a port queues behind the others on one connection, so six meters
at 2400 baud cannot all be polled every 10 seconds. Raise the scan interval
under *Configure*, or move the bus to a higher baud rate — all of the meters on
it, together.

**A meter rejects a block read with an illegal-data-address exception.** Some
units answer a narrower range than their protocol document promises. Its model
class in `custom_components/eastron_sdm/sdm/` carries `register_ranges` and
`max_span`; cutting those back to what the unit answers fixes it, and is worth
reporting so the map can be corrected.


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
3. Add any new field names to `SENSORS` in `sensor.py` and to `strings.json`,
   and give each one an icon in `icons.json` if it carries no device class.
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
every rule through platinum is met or exempt, with a reason on each exemption in
[`custom_components/eastron_sdm/quality_scale.yaml`](custom_components/eastron_sdm/quality_scale.yaml).
The scale gates core integrations and binds nothing here, so treat it as a
checklist that was worked through rather than as a badge.

## Licence

Apache License 2.0. See [LICENSE](LICENSE).
