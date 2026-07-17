# ipace-obd

Read HV battery telemetry and diagnostic trouble codes (DTCs) from a **2019 Jaguar
I-PACE** over a **BLE OBD-II adapter** (e.g. Veepeak OBDCheck BLE), directly from
Python on your own computer.

> **Run this on your computer, next to the car** - not in a cloud/remote environment.
> Bluetooth Low Energy only works over a short physical range, so whatever machine
> runs this tool needs a real Bluetooth radio and needs to actually be near the
> Veepeak dongle that's plugged into the car.

## What this does

1. **Connects** to the Veepeak (or any ELM327-compatible BLE OBD-II adapter) over
   Bluetooth Low Energy.
2. **Reads HV battery data**: pack voltage/current, SOC (avg/min/max), SOH
   (capacity + power), min/max cell voltage, pack temperatures (avg/min/max + all 6
   physical plate sensors), coolant in/out temps, and max regen power - using the
   Jaguar I-PACE's manufacturer-specific diagnostic PIDs (see [Sources](#sources)
   below).
3. **Reads and clears fault codes (DTCs)**:
   - Generic OBD-II ("check engine light") codes, and
   - A full per-module scan/clear (BECM, ABS, BCM, PCM, etc.) similar to what a
     dealer-level scan tool does, since most I-PACE faults live in body/chassis/
     battery modules rather than the legacy emissions-OBD layer.

## Hardware & compatibility notes

- Tested against the **Veepeak OBDCheck BLE** (ELM327 v1.5 chipset, GATT service
  `FFF0`). The BLE transport auto-detects the write/notify characteristics so it
  should also work with most other ELM327-over-BLE clones (including the common
  `49535343-...` ISSC/CC254x-based boards).
- The adapter must support **ISO 15765-4 CAN**, which the I-PACE uses (the Veepeak
  OBDCheck BLE does).
- **iOS**: Apple's Core Bluetooth stack doesn't allow arbitrary Python BLE access the
  way this tool needs. Run this on **macOS, Windows, or Linux** instead. (`bleak`,
  the BLE library used here, supports all three.)
- The car's OBD-II port only powers up the CAN bus when the car is "awake." If you
  get no response, try opening a door, pressing the brake pedal, or putting the car
  in "Drive-ready" accessory mode first.

## Setup

```bash
# 1. Clone/download this project, then from its root:
python3 -m venv .venv
source .venv/bin/activate        # on Windows: .venv\Scripts\activate

# 2. Install it
pip install -e .
```

### Linux-specific notes

- You need BlueZ (`bluetoothd`) running, which is standard on most desktop distros.
- If you get permission errors, either run with `sudo` or grant your user Bluetooth
  capabilities: `sudo setcap 'cap_net_raw,cap_net_admin+eip' $(readlink -f $(which python3))`.

### Windows-specific notes

- Windows 10 1809+ or Windows 11 with a Bluetooth LE capable adapter.
- You do **not** need to manually pair the Veepeak in Windows Bluetooth settings -
  `bleak` connects directly, and pairing can sometimes interfere.

### macOS-specific notes

- The first time you run this, macOS will prompt for Bluetooth permission for your
  terminal/Python - allow it (System Settings -> Privacy & Security -> Bluetooth).

## Usage

Plug the Veepeak into the I-PACE's OBD-II port (under the dash, driver's side) and
make sure the car is awake (see note above).

### 1. Find the adapter's BLE address

```bash
ipace-obd scan
```

This lists nearby BLE devices whose name looks like an OBD adapter (e.g.
`VEEPEAK`), along with the BLE address you'll pass to every other command. If it
doesn't show up, try `ipace-obd scan --all` to see every nearby BLE device.

### 2. Sanity-check the connection

```bash
ipace-obd info --address AA:BB:CC:DD:EE:FF
```

Connects, initializes the ELM327, and prints the adapter ID string plus the car's
12V system voltage as reported by the adapter - a good first test that the BLE link
and ELM327 are both working before trying anything car-specific.

### 3. Read all battery data

```bash
ipace-obd battery --address AA:BB:CC:DD:EE:FF
```

Prints a table of every known HV battery PID (SOC, SOH, voltage, current, cell
voltages, pack/plate temperatures, coolant temps, max regen). Add `--csv log.csv` to
append the reading to a CSV file, or `--only soc_avg --only pack_voltage` to read
just specific PIDs (see `ipace-obd list-pids` for all available keys).

To continuously log data (e.g. during a drive or a charge session):

```bash
ipace-obd monitor --address AA:BB:CC:DD:EE:FF --csv drive_log.csv --interval 5
```

### 4. Read fault codes

```bash
ipace-obd dtc read --address AA:BB:CC:DD:EE:FF
```

By default this checks both the generic OBD-II layer *and* scans the priority set
of modules (BECM, BCCM, PCM, ABS, BCM, inverters, DC-DC, cluster, HVAC, TCU) for
UDS-reported fault codes. Use `--ecus all` to scan literally every known module
(slower), or `--ecus BECM,ABS` to target specific ones. Use `--scope legacy` or
`--scope modules` to run only one half of the scan.

### 5. Clear (reset) fault codes

```bash
ipace-obd dtc clear --address AA:BB:CC:DD:EE:FF
```

Clears the generic OBD-II DTCs plus all UDS DTCs on the priority module set (same
`--ecus` option as above applies). You'll be asked to confirm first (skip with
`--yes`).

> **Warning:** clearing DTCs does not fix the underlying issue. If the condition
> that caused a code is still present, it will likely come back (sometimes
> immediately, sometimes after the next drive cycle).

### Raw requests

For exploring/verifying PIDs yourself:

```bash
ipace-obd raw --address AA:BB:CC:DD:EE:FF 7E4 22490F
```

Sends a raw hex payload to the given CAN header and prints the adapter's raw reply.

## PID reference & sources

This is a hobbyist EV, not a factory-documented one - Jaguar Land Rover has not
published these PIDs. The addresses and formulas here come from two independent,
cross-checked community sources:

1. **[Open Vehicles Monitoring System (OVMS) v3](https://github.com/openvehicles/Open-Vehicle-Monitoring-System-3/blob/master/vehicle/OVMS.V3/components/vehicle_jaguaripace/src/ipace_obd_pids.h)**
   Jaguar I-PACE driver, (C) 2021 Didier Ernotte - production code that confirms PID
   *names/addresses* per ECU.
2. Jaguar I-PACE owner forum threads (community-derived scaling *formulas*,
   contributors include Kermit68, Dernotte, ANBO, and others):
   - <https://www.openvehicles.com/node/2423>
   - <https://www.ipaceforums.co.uk/threads/canbus-and-pid-for-the-ipace.4280/>
   - <https://www.ipaceforums.co.uk/threads/obd-ii-pid-and-torque-pro.4581/>
   - <https://www.ipaceforums.co.uk/threads/check-battery-health.5682/>

Run `ipace-obd list-pids` to see the full list with each PID's request code and
whether its scaling formula is independently confirmed ("verified") or just a
best-effort guess ("unconfirmed" - shown with a caveat note in the `battery`
command's output too). SOH readings in particular are known from the forums to
drift and should be treated as a rough trend indicator, not a precise measurement.

All battery PIDs are UDS `ReadDataByIdentifier` (Mode `0x22`) requests sent to the
BECM (Battery Energy Control Module) at CAN header `0x7E4`, except `ambient_temp`
(HVAC module, `0x733`) and `vehicle_speed` (BCM, `0x726`).

## Project layout

```
ipace_obd/
  ble_transport.py    BLE scanning + ELM327-over-BLE GATT transport (bleak)
  elm327.py           ELM327 AT-command driver (init, header switching, requests)
  uds.py              UDS/OBD response parsing + legacy & UDS DTC decoding
  dtc.py              Read/clear DTCs (legacy broadcast + per-ECU UDS scan)
  session.py          High-level session tying transport+ELM327+PID decoding together
  pids/
    ecus.py           Known I-PACE ECU CAN addresses (BECM, ABS, BCM, PCM, ...)
    ipace_battery.py  Battery PID definitions + decode formulas + source notes
  cli.py               `ipace-obd` command line interface
tests/                 Unit tests for parsing/decoding logic (no hardware required)
```

## Running the tests

```bash
pip install -r requirements-dev.txt
pytest
```

The test suite only exercises pure parsing/decoding logic and fake transports - it
does not require a BLE adapter or the car, so it runs anywhere (including CI).
