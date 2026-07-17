"""Thin async driver for talking ELM327 AT-commands + OBD/UDS requests over a transport."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from .ble_transport import Elm327BleTransport

logger = logging.getLogger(__name__)


class Elm327Error(RuntimeError):
    """Raised when the adapter reports an error (e.g. NO DATA, CAN ERROR, UNABLE TO CONNECT)."""


_ERROR_TOKENS = (
    "NO DATA",
    "ERROR",
    "UNABLE TO CONNECT",
    "BUS INIT",
    "CAN ERROR",
    "STOPPED",
    "?",
)


@dataclass
class Elm327Info:
    id_string: str = ""
    voltage: str = ""


class Elm327:
    """High level ELM327 command driver. Wraps a transport (BLE, serial, whatever)."""

    def __init__(self, transport: Elm327BleTransport):
        self._t = transport
        self._current_header: Optional[str] = None

    async def initialize(self, protocol: str = "0") -> Elm327Info:
        """Reset the adapter and configure it for clean CAN communication with the I-PACE.

        protocol: ELM327 ``ATSP<n>`` value. ``0`` = automatic. The I-PACE uses
        ISO 15765-4 CAN (11-bit ID, 500 kbps), which is protocol ``6``, but automatic
        detection works fine and is safer across ELM327 clone firmware quirks.
        """
        await self._cmd("ATZ")  # full reset
        await self._cmd("ATE0")  # echo off
        await self._cmd("ATL0")  # linefeeds off
        await self._cmd("ATS0")  # spaces off (denser, easier to parse)
        await self._cmd("ATH1")  # headers ON - we need to know which ECU answered
        await self._cmd("ATCAF1")  # CAN auto formatting on (handles ISO-TP framing for us)
        await self._cmd(f"ATSP{protocol}")
        id_string = await self._cmd("ATI")
        voltage = await self._cmd("ATRV")
        self._current_header = None
        return Elm327Info(id_string=id_string, voltage=voltage)

    async def set_header(self, header: str) -> None:
        """Set the CAN transmit header (target ECU address), e.g. '7E4' for the BECM."""
        header = header.upper()
        if header == self._current_header:
            return
        await self._cmd(f"ATSH{header}")
        self._current_header = header

    async def request(self, header: str, hex_payload: str) -> str:
        """Send a raw hex request (e.g. mode+PID, like '22490F') to the given ECU header."""
        await self.set_header(header)
        return await self._cmd(hex_payload, allow_no_data=True)

    async def _cmd(self, command: str, allow_no_data: bool = False) -> str:
        reply = await self._t.send_raw(command)
        upper = reply.upper()
        if not allow_no_data:
            for token in _ERROR_TOKENS:
                if token in upper:
                    raise Elm327Error(f"Adapter error for {command!r}: {reply!r}")
        return reply
