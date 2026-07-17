"""Known Jaguar I-PACE ECU (module) CAN addresses.

Source: reverse-engineered and published by the Open Vehicles Monitoring System (OVMS)
project, Jaguar I-PACE component, (C) 2021 Didier Ernotte, MIT-style licensed:
https://github.com/openvehicles/Open-Vehicle-Monitoring-System-3/blob/master/vehicle/OVMS.V3/components/vehicle_jaguaripace/src/ipace_obd_pids.h

Also cross-referenced against the Jaguar I-PACE community forum threads:
  - https://www.ipaceforums.co.uk/threads/canbus-and-pid-for-the-ipace.4280/
  - https://www.openvehicles.com/node/2423

The I-PACE uses an 11-bit CAN identifier scheme where each ECU listens on its own
"physical request" address and replies on request+0x8 ("physical response" address) -
this is the standard convention used across most modern OBD-II/UDS capable ECUs.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Ecu:
    name: str
    description: str
    tx: int  # request (transmit) CAN ID

    @property
    def rx(self) -> int:
        return self.tx + 0x8

    @property
    def tx_hex(self) -> str:
        return f"{self.tx:03X}"

    @property
    def rx_hex(self) -> str:
        return f"{self.rx:03X}"


_ECU_LIST = [
    Ecu("IPMA", "Image Processing Module A", 0x706),
    Ecu("CHCM", "Chassis Control Module", 0x710),
    Ecu("SDLC", "Unknown (SDLC gateway?)", 0x716),
    Ecu("IPC", "Instrument Panel Cluster", 0x720),
    Ecu("BCM", "Body Control Module / Gateway Module", 0x726),
    Ecu("PSCM", "Power Steering Control Module", 0x730),
    Ecu("RFA", "Remote Function Actuator", 0x731),
    Ecu("GSM", "Gear Shift Control Module", 0x732),
    Ecu("HVAC", "HVAC Control Module", 0x733),
    Ecu("HCM", "Headlamp Control Module", 0x734),
    Ecu("PAM", "Parking Assist Control Module", 0x736),
    Ecu("RCM", "Restraints Control Module", 0x737),
    Ecu("DDM", "Driver Door Module", 0x740),
    Ecu("PDM", "Passenger Door Module", 0x741),
    Ecu("DRDM", "Driver Rear Door Module", 0x742),
    Ecu("PRDM", "Passenger Rear Door Module", 0x743),
    Ecu("DSM", "Driver Seat Module", 0x744),
    Ecu("EPICC", "Rear Electric Power Inverter Converter", 0x746),
    Ecu("EPICB", "Front Electric Power Inverter Converter", 0x747),
    Ecu("TPMS", "Tire Pressure Monitoring System", 0x751),
    Ecu("OMM", "Occupant Monitoring Module", 0x752),
    Ecu("DCDC", "DC-DC Converter", 0x753),
    Ecu("TCU", "Telematics Control Unit", 0x754),
    Ecu("ASCM", "Adaptive Speed Control Module", 0x764),
    Ecu("RGTM", "Rear Gate / Trunk Module", 0x775),
    Ecu("RHVAC", "Rear HVAC", 0x785),
    Ecu("ATCM", "Jaguar Drive Selector / Switchpack", 0x792),
    Ecu("SASM", "Steering Angle Sensing Module", 0x797),
    Ecu("IDMA", "Interactive Display Module", 0x7A2),
    Ecu("PSM", "Passenger Seat Module", 0x7A3),
    Ecu("AAM", "Audio Amplifier Module", 0x7A4),
    Ecu("CMR", "Camera Module Rear", 0x7B1),
    Ecu("HUD", "Head-Up Display", 0x7B2),
    Ecu("IMC", "Infotainment Master Control", 0x7B3),
    Ecu("HCMB", "Headlight Control Module B", 0x7C3),
    Ecu("SODL", "Side Object Detection - Left", 0x7C4),
    Ecu("SODR", "Side Object Detection - Right", 0x7C6),
    Ecu("PCM", "Powertrain Control Module", 0x7E0),
    Ecu("BBM", "Brake Booster Module", 0x7E2),
    Ecu("BECM", "Battery Energy Control Module (HV battery / BMS)", 0x7E4),
    Ecu("BCCM", "Battery Charger Control Module (onboard AC charger)", 0x7E5),
    Ecu("ABS", "Anti-lock Braking System", 0x7E6),
]

ECUS: dict[str, Ecu] = {e.name: e for e in _ECU_LIST}

# The handful of modules most relevant to "read every fault code" style scans and to HV
# battery telemetry. Scanning *every* known ECU works too (see ECUS above) but is slower
# and some non-safety modules may not be present/populated on every model year/trim.
PRIORITY_ECUS = ["BECM", "BCCM", "PCM", "ABS", "BCM", "EPICB", "EPICC", "DCDC", "IPC", "HVAC", "TCU"]
