"""Reading and clearing diagnostic trouble codes (DTCs).

Two complementary approaches are implemented:

1. Legacy generic OBD-II (broadcast to 0x7DF, modes 0x03/0x07/0x0A to read, 0x04 to
   clear). This is what a generic "check engine light" code reader does. On a modern
   EV like the I-PACE this mostly covers the powertrain/emissions-adjacent module and
   is a quick universal check.

2. Manufacturer UDS diagnostics (ISO 14229) per-ECU: Mode 0x19 sub-function 0x02
   (reportDTCByStatusMask, mask 0xFF = all) sent directly to each module's physical
   address (e.g. 0x7E4 BECM, 0x7E6 ABS, 0x726 BCM...), and Mode 0x14
   (ClearDiagnosticInformation, group 0xFFFFFF = all groups) to clear. This is closer
   to what a dealer-level scan tool does when it scans "all modules", and is the only
   way to see faults stored in body/chassis/battery modules rather than just the
   legacy emissions-OBD layer.
"""

from __future__ import annotations

from dataclasses import dataclass

from .elm327 import Elm327, Elm327Error
from .pids.ecus import ECUS, Ecu
from .uds import Dtc, decode_dtc_status, decode_legacy_dtc_list, decode_uds_dtc_list, find_legacy_response

BROADCAST_HEADER = "7DF"

_LEGACY_MODES = {
    "stored": 0x03,
    "pending": 0x07,
    "permanent": 0x0A,
}


@dataclass
class EcuDtcResult:
    ecu: Ecu
    dtcs: list[Dtc]
    error: str | None = None


async def read_legacy_dtcs(elm: Elm327, category: str = "stored") -> list[Dtc]:
    """Read generic OBD-II DTCs (mode 0x03/0x07/0x0A) via broadcast header 0x7DF."""
    mode = _LEGACY_MODES[category]
    reply = await elm.request(BROADCAST_HEADER, f"{mode:02X}")
    payload = find_legacy_response(reply, mode)
    if payload is None:
        return []
    return decode_legacy_dtc_list(payload)


async def clear_legacy_dtcs(elm: Elm327) -> str:
    """Clear generic OBD-II DTCs / turn off the MIL (mode 0x04, broadcast)."""
    return await elm.request(BROADCAST_HEADER, "04")


async def read_ecu_dtcs(elm: Elm327, ecu: Ecu) -> EcuDtcResult:
    """Read UDS DTCs (all status types) from a single ECU via Mode 0x19/0x02."""
    try:
        reply = await elm.request(ecu.tx_hex, "190202")
        from .uds import extract_bytes

        data = extract_bytes(reply)
        # Look for positive response 0x59 0x02 <statusAvailabilityMask> <records...>
        for i in range(len(data) - 2):
            if data[i] == 0x59 and data[i + 1] == 0x02:
                payload = bytes(data[i + 3 :])
                return EcuDtcResult(ecu=ecu, dtcs=decode_uds_dtc_list(payload))
        return EcuDtcResult(ecu=ecu, dtcs=[])
    except Elm327Error as exc:
        return EcuDtcResult(ecu=ecu, dtcs=[], error=str(exc))
    except TimeoutError as exc:
        return EcuDtcResult(ecu=ecu, dtcs=[], error=str(exc))
    except ValueError:
        # No matching frame found at all (module didn't respond in an expected shape).
        return EcuDtcResult(ecu=ecu, dtcs=[])


async def scan_ecus_for_dtcs(elm: Elm327, ecu_names: list[str]) -> list[EcuDtcResult]:
    results = []
    for name in ecu_names:
        ecu = ECUS[name]
        results.append(await read_ecu_dtcs(elm, ecu))
    return results


async def clear_ecu_dtcs(elm: Elm327, ecu: Ecu) -> str:
    """Clear all DTCs on a single ECU via Mode 0x14 (ClearDiagnosticInformation), group 0xFFFFFF."""
    return await elm.request(ecu.tx_hex, "14FFFFFF")


async def clear_all(elm: Elm327, ecu_names: list[str]) -> dict[str, str]:
    """Clear both the legacy OBD DTCs and UDS DTCs on every given ECU. Returns a dict of
    target -> raw adapter reply (or error text) for logging/debugging."""
    results: dict[str, str] = {}
    try:
        results["legacy(7DF)"] = await clear_legacy_dtcs(elm)
    except (Elm327Error, TimeoutError) as exc:
        results["legacy(7DF)"] = f"ERROR: {exc}"
    for name in ecu_names:
        ecu = ECUS[name]
        try:
            results[ecu.name] = await clear_ecu_dtcs(elm, ecu)
        except (Elm327Error, TimeoutError) as exc:
            results[ecu.name] = f"ERROR: {exc}"
    return results


def describe_status(status: int | None) -> str:
    if status is None:
        return ""
    flags = decode_dtc_status(status)
    return ",".join(flags) if flags else "none"
