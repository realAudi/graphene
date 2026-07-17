"""Helpers for parsing ELM327 text responses into raw UDS/OBD payload bytes.

ELM327 clones vary quite a bit in exactly how they format multi-frame ISO-TP CAN
responses (even with the same AT settings), so instead of trying to precisely
re-implement ISO-TP framing, we take a pragmatic approach used by many hobbyist
tools: tokenize every line into hex bytes, drop tokens that look like a CAN
arbitration ID (3-4 hex chars, appearing as the first token on a line when headers
are on), concatenate everything else into one byte stream, then search for the
expected UDS/OBD positive-response marker bytes anywhere in that stream.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


class NegativeResponseError(RuntimeError):
    def __init__(self, service: int, nrc: int):
        self.service = service
        self.nrc = nrc
        super().__init__(f"Negative response to service 0x{service:02X}: NRC 0x{nrc:02X} ({nrc_name(nrc)})")


_NRC_NAMES = {
    0x10: "generalReject",
    0x11: "serviceNotSupported",
    0x12: "subFunctionNotSupported",
    0x13: "incorrectMessageLengthOrInvalidFormat",
    0x14: "responseTooLong",
    0x21: "busyRepeatRequest",
    0x22: "conditionsNotCorrect",
    0x24: "requestSequenceError",
    0x31: "requestOutOfRange",
    0x33: "securityAccessDenied",
    0x35: "invalidKey",
    0x36: "exceedNumberOfAttempts",
    0x37: "requiredTimeDelayNotExpired",
    0x78: "requestCorrectlyReceived-ResponsePending",
}


def nrc_name(nrc: int) -> str:
    return _NRC_NAMES.get(nrc, "unknown")


def _is_header_token(token: str) -> bool:
    # 11-bit CAN IDs print as 3 hex chars (e.g. 7EC); some adapters zero-pad to 4.
    return len(token) in (3, 4) and all(c in "0123456789ABCDEFabcdef" for c in token)


def extract_bytes(raw_response: str) -> list[int]:
    """Tokenize an ELM327 reply into a flat list of data bytes, dropping header tokens
    and any leading multi-frame length/index tokens ELM327 sometimes still emits.
    """
    data: list[int] = []
    for line in raw_response.splitlines():
        tokens = line.strip().split()
        if not tokens:
            continue
        # Drop a leading CAN-ID header token (3-4 hex chars) at the start of the line.
        if _is_header_token(tokens[0]):
            tokens = tokens[1:]
        for tok in tokens:
            if len(tok) == 2 and all(c in "0123456789ABCDEFabcdef" for c in tok):
                data.append(int(tok, 16))
            # Ignore anything else (stray length/index bytes >2 chars, "SEARCHING...", etc.)
    return data


def find_uds_response(raw_response: str, service: int, did: int, did_len: int = 2) -> bytes:
    """Find a positive UDS response (service+0x40) that echoes back `did`, and return
    the payload bytes that follow it.

    Raises NegativeResponseError if a negative response (0x7F <service> <NRC>) is seen
    instead, or ValueError if no matching response could be found at all.
    """
    data = extract_bytes(raw_response)
    positive = (service + 0x40) & 0xFF
    did_bytes = did.to_bytes(did_len, "big")

    for i in range(len(data)):
        if data[i] == 0x7F and i + 2 < len(data) and data[i + 1] == service:
            raise NegativeResponseError(service, data[i + 2])
        if data[i] == positive and data[i + 1 : i + 1 + did_len] == list(did_bytes):
            start = i + 1 + did_len
            return bytes(data[start:])
    raise ValueError(f"No matching response for service 0x{service:02X} DID 0x{did:0{did_len*2}X} in: {raw_response!r}")


def find_legacy_response(raw_response: str, mode: int) -> Optional[bytes]:
    """Find a positive legacy-OBD response (mode+0x40) and return payload bytes after it
    (including the echoed PID, if any - caller decides how to slice further)."""
    data = extract_bytes(raw_response)
    positive = (mode + 0x40) & 0xFF
    for i, b in enumerate(data):
        if b == positive:
            return bytes(data[i + 1 :])
    return None


# ---------------------------------------------------------------------------
# Legacy (SAE J2012 / ISO 15031-6) 2-byte DTC decoding, used by Modes 03/07/0A
# ---------------------------------------------------------------------------

_DTC_CATEGORY = {0b00: "P", 0b01: "C", 0b10: "B", 0b11: "U"}


@dataclass
class Dtc:
    code: str
    raw: str
    status: Optional[int] = None
    subtype_byte: Optional[int] = None

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.code


def decode_legacy_dtc(byte1: int, byte2: int) -> Dtc:
    category = _DTC_CATEGORY[(byte1 >> 6) & 0b11]
    digit1 = (byte1 >> 4) & 0b11
    digit2 = byte1 & 0x0F
    code = f"{category}{digit1}{digit2:X}{byte2:02X}"
    return Dtc(code=code, raw=f"{byte1:02X}{byte2:02X}")


def decode_legacy_dtc_list(payload: bytes) -> list[Dtc]:
    """Decode a Mode 03/07/0A payload (2 bytes per DTC; some adapters prefix a count byte
    which we detect heuristically: if the byte count is odd, the first byte is a count)."""
    b = list(payload)
    if len(b) % 2 == 1:
        b = b[1:]
    codes = []
    for i in range(0, len(b) - 1, 2):
        if b[i] == 0 and b[i + 1] == 0:
            continue  # padding
        codes.append(decode_legacy_dtc(b[i], b[i + 1]))
    return codes


# ---------------------------------------------------------------------------
# UDS (ISO 14229) 3-byte DTC + 1 status-byte decoding, used by Mode 0x19/0x14
# on individual body/chassis ECUs (BECM, BCM, ABS, etc.)
# ---------------------------------------------------------------------------

_DTC_STATUS_BITS = {
    0: "testFailed",
    1: "testFailedThisOperationCycle",
    2: "pendingDTC",
    3: "confirmedDTC",
    4: "testNotCompletedSinceLastClear",
    5: "testFailedSinceLastClear",
    6: "testNotCompletedThisOperationCycle",
    7: "warningIndicatorRequested",
}


def decode_dtc_status(status: int) -> list[str]:
    return [name for bit, name in _DTC_STATUS_BITS.items() if status & (1 << bit)]


def decode_uds_dtc(byte1: int, byte2: int, byte3: int, status: int) -> Dtc:
    """byte1/byte2 encode a standard SAE DTC exactly like the legacy 2-byte format; byte3
    is the manufacturer "failure type byte" (subtype - e.g. high/low/open/short) which we
    surface as a hex suffix since we don't have JLR's proprietary subtype text tables."""
    base = decode_legacy_dtc(byte1, byte2)
    code = f"{base.code}-{byte3:02X}"
    return Dtc(code=code, raw=f"{byte1:02X}{byte2:02X}{byte3:02X}", status=status, subtype_byte=byte3)


def decode_uds_dtc_list(payload: bytes) -> list[Dtc]:
    """Decode a Mode 0x19 sub-function 0x02 (reportDTCByStatusMask) response payload,
    *excluding* the leading statusAvailabilityMask byte (caller should strip it first).
    Each DTC record is 4 bytes: 3 bytes DTC + 1 status byte."""
    b = list(payload)
    out = []
    for i in range(0, len(b) - 3, 4):
        out.append(decode_uds_dtc(b[i], b[i + 1], b[i + 2], b[i + 3]))
    return out
