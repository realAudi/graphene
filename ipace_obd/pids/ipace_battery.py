"""Jaguar I-PACE HV battery (BECM) PIDs and decode formulas.

These are manufacturer-specific UDS "ReadDataByIdentifier" (service 0x22) PIDs, not
standard SAE J1979 PIDs, so no factory documentation is publicly available. This list
is compiled from community reverse-engineering, cross-checked across two independent
sources:

  1. The Open Vehicles Monitoring System (OVMS) v3 Jaguar I-PACE driver (production code,
     MIT-style license), (C) 2021 Didier Ernotte:
     https://github.com/openvehicles/Open-Vehicle-Monitoring-System-3/blob/master/vehicle/OVMS.V3/components/vehicle_jaguaripace/src/ipace_obd_pids.h
     -> gives us the confirmed PID *names/addresses*.

  2. Jaguar I-PACE owner forum threads (community decode formulas), primarily:
     https://www.openvehicles.com/node/2423
     https://www.ipaceforums.co.uk/threads/canbus-and-pid-for-the-ipace.4280/
     https://www.ipaceforums.co.uk/threads/obd-ii-pid-and-torque-pro.4581/
     -> gives us the scaling *formulas* (contributors: Kermit68, Dernotte, ANBO, and others).

All requests are UDS Mode 0x22 (ReadDataByIdentifier) sent to the BECM at CAN header
0x7E4 (response 0x7EC), unless otherwise noted. Formulas marked ``verified=False`` are
PIDs whose *address* is confirmed by OVMS but whose scaling formula was not confirmed in
the forum threads used for this project - the raw bytes are still shown so you can derive/
verify the formula yourself by comparing against a known state (e.g. SOC shown on the
instrument cluster).

IMPORTANT: this is reverse-engineered, unofficial data from enthusiast communities, not
from Jaguar Land Rover. Treat absolute values (especially SOH) with healthy skepticism -
cross-check trends over time rather than trusting a single snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .ecus import ECUS, Ecu

Decoder = Callable[[bytes], float]


def _u16(data: bytes) -> int:
    return (data[0] << 8) | data[1]


@dataclass(frozen=True)
class PidDef:
    key: str
    name: str
    ecu: Ecu
    pid: int
    decode: Decoder
    unit: str = ""
    length: int = 2  # expected number of raw data bytes
    mode: int = 0x22
    verified: bool = True
    source: str = "community"
    notes: str = ""

    @property
    def pid_hex(self) -> str:
        return f"{self.pid:04X}"

    @property
    def request_hex(self) -> str:
        return f"{self.mode:02X}{self.pid_hex}"


BECM = ECUS["BECM"]
BCM = ECUS["BCM"]
HVAC = ECUS["HVAC"]

BATTERY_PIDS: list[PidDef] = [
    PidDef(
        key="soc_avg",
        name="State of Charge (avg)",
        ecu=BECM,
        pid=0x4910,
        decode=lambda d: _u16(d) / 100.0,
        unit="%",
        notes="True battery SOC (not the dash-displayed usable %). Pack is never charged "
        "above ~96-97%% (cell voltage 4.15V) per forum consensus.",
    ),
    PidDef(
        key="soc_min",
        name="State of Charge (min cell group)",
        ecu=BECM,
        pid=0x4911,
        decode=lambda d: _u16(d) / 100.0,
        unit="%",
    ),
    PidDef(
        key="soc_max",
        name="State of Charge (max cell group)",
        ecu=BECM,
        pid=0x4914,
        decode=lambda d: _u16(d) / 100.0,
        unit="%",
    ),
    PidDef(
        key="soh_capacity_avg",
        name="State of Health - Capacity (avg)",
        ecu=BECM,
        pid=0x4918,
        decode=lambda d: d[0] / 2.0,
        unit="%",
        length=1,
        notes="SOH estimation is known to drift with driving/charging style; treat as a "
        "trend indicator, not an absolute capacity test result.",
    ),
    PidDef(
        key="soh_capacity_max",
        name="State of Health - Capacity (max)",
        ecu=BECM,
        pid=0x4919,
        decode=lambda d: d[0] / 2.0,
        unit="%",
        length=1,
    ),
    PidDef(
        key="soh_capacity_min",
        name="State of Health - Capacity (min)",
        ecu=BECM,
        pid=0x491A,
        decode=lambda d: d[0] / 2.0,
        unit="%",
        length=1,
    ),
    PidDef(
        key="soh_power_avg",
        name="State of Health - Power (avg)",
        ecu=BECM,
        pid=0x4915,
        decode=lambda d: d[0] / 2.0,
        unit="%",
        length=1,
        verified=False,
        notes="Address confirmed by OVMS; scaling assumed same as capacity-SOH (A/2) but "
        "not independently confirmed on forums - verify before trusting.",
    ),
    PidDef(
        key="soh_power_max",
        name="State of Health - Power (max)",
        ecu=BECM,
        pid=0x4916,
        decode=lambda d: d[0] / 2.0,
        unit="%",
        length=1,
        verified=False,
    ),
    PidDef(
        key="soh_power_min",
        name="State of Health - Power (min)",
        ecu=BECM,
        pid=0x4917,
        decode=lambda d: d[0] / 2.0,
        unit="%",
        length=1,
        verified=False,
    ),
    PidDef(
        key="pack_voltage",
        name="HV Battery Pack Voltage",
        ecu=BECM,
        pid=0x490F,
        decode=lambda d: _u16(d) / 100.0,
        unit="V",
    ),
    PidDef(
        key="pack_current",
        name="HV Battery Pack Current",
        ecu=BECM,
        pid=0x490C,
        decode=lambda d: (_u16(d) - 32768) / 40.0,
        unit="A",
        notes="Sign convention not fully confirmed by community; original reporter noted "
        "positive readings while charging. Verify polarity against a known charge/discharge "
        "state before relying on sign.",
        verified=False,
    ),
    PidDef(
        key="cell_voltage_max",
        name="Max Individual Cell Voltage",
        ecu=BECM,
        pid=0x4903,
        decode=lambda d: _u16(d) / 1000.0,
        unit="V",
    ),
    PidDef(
        key="cell_voltage_min",
        name="Min Individual Cell Voltage",
        ecu=BECM,
        pid=0x4904,
        decode=lambda d: _u16(d) / 1000.0,
        unit="V",
    ),
    PidDef(
        key="temp_max",
        name="Battery Temperature (max)",
        ecu=BECM,
        pid=0x4905,
        decode=lambda d: d[0] / 2.0 - 40.0,
        unit="\u00b0C",
        length=1,
    ),
    PidDef(
        key="temp_min",
        name="Battery Temperature (min)",
        ecu=BECM,
        pid=0x4906,
        decode=lambda d: d[0] / 2.0 - 40.0,
        unit="\u00b0C",
        length=1,
    ),
    PidDef(
        key="temp_avg",
        name="Battery Temperature (avg)",
        ecu=BECM,
        pid=0x4907,
        decode=lambda d: d[0] / 2.0 - 40.0,
        unit="\u00b0C",
        length=1,
    ),
    PidDef(
        key="max_regen",
        name="Max Regen Power Available",
        ecu=BECM,
        pid=0x4913,
        decode=lambda d: _u16(d) / 100.0,
        unit="kW (assumed)",
        verified=False,
        notes="Unit not confirmed by community sources; raw scaling is (A*256+B)/100.",
    ),
    PidDef(
        key="coolant_outlet_temp",
        name="Battery Coolant Outlet Temperature",
        ecu=BECM,
        pid=0x491B,
        decode=lambda d: d[0] - 40.0,
        unit="\u00b0C",
        length=1,
    ),
    PidDef(
        key="coolant_inlet_temp",
        name="Battery Coolant Inlet Temperature",
        ecu=BECM,
        pid=0x491C,
        decode=lambda d: d[0] - 40.0,
        unit="\u00b0C",
        length=1,
    ),
    PidDef(
        key="cabin_temp",
        name="Cabin Temperature",
        ecu=BECM,
        pid=0xDD04,
        decode=lambda d: d[0] - 40.0,
        unit="\u00b0C",
        length=1,
        notes="OVMS lists this PID address without a dedicated ECU comment separator; "
        "queried here on BECM (0x7E4) as reported on the forums. Not battery data, kept "
        "for convenience/cross-checking cabin vs pack temps.",
    ),
    PidDef(
        key="ambient_temp",
        name="Ambient (Outside) Temperature",
        ecu=HVAC,
        pid=0x9924,
        decode=lambda d: d[0] * 0.5 - 40.0,
        unit="\u00b0C",
        length=1,
    ),
    PidDef(
        key="vehicle_speed",
        name="Vehicle Speed",
        ecu=BCM,
        pid=0xDD09,
        decode=lambda d: float(d[0]),
        unit="km/h (assumed)",
        length=1,
        verified=False,
    ),
]

# 6x individual battery "plate" (module group) temperature sensors: 0x492B..0x4930
for _i, _pid in enumerate(range(0x492B, 0x4931)):
    BATTERY_PIDS.append(
        PidDef(
            key=f"plate_temp_{_i + 1}",
            name=f"Battery Plate {_i + 1} Temperature",
            ecu=BECM,
            pid=_pid,
            decode=lambda d: d[0] - 40.0,
            unit="\u00b0C",
            length=1,
            notes="One of 6 physical temperature sensor locations across the battery pack.",
        )
    )

BATTERY_PIDS_BY_KEY: dict[str, PidDef] = {p.key: p for p in BATTERY_PIDS}
