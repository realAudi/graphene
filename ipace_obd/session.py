"""High level session: connect to the BLE adapter, init ELM327, and read named PIDs."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from .ble_transport import DiscoveredAdapter, Elm327BleTransport, scan_all, scan_for_adapters
from .elm327 import Elm327, Elm327Error, Elm327Info
from .pids.ipace_battery import BATTERY_PIDS, PidDef
from .uds import NegativeResponseError, find_uds_response

logger = logging.getLogger(__name__)


@dataclass
class PidReading:
    pid: PidDef
    value: Optional[float]
    raw: bytes = b""
    error: Optional[str] = None

    @property
    def formatted(self) -> str:
        if self.error:
            return f"ERR: {self.error}"
        if self.value is None:
            return "n/a"
        return f"{self.value:g} {self.pid.unit}".strip()


class IPaceSession:
    def __init__(self, transport: Elm327BleTransport):
        self._transport = transport
        self.elm = Elm327(transport)
        self.info: Optional[Elm327Info] = None

    @classmethod
    async def connect_to(cls, address_or_device, response_timeout: float = 5.0) -> "IPaceSession":
        transport = Elm327BleTransport(address_or_device, response_timeout=response_timeout)
        await transport.connect()
        session = cls(transport)
        session.info = await session.elm.initialize()
        return session

    async def close(self) -> None:
        await self._transport.disconnect()

    async def __aenter__(self) -> "IPaceSession":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def read_pid(self, pid: PidDef) -> PidReading:
        try:
            reply = await self.elm.request(pid.ecu.tx_hex, pid.request_hex)
            payload = find_uds_response(reply, pid.mode, pid.pid)
            if len(payload) < pid.length:
                return PidReading(pid=pid, value=None, raw=payload, error=f"short response ({len(payload)} bytes)")
            value = pid.decode(payload[: pid.length])
            return PidReading(pid=pid, value=value, raw=payload)
        except NegativeResponseError as exc:
            return PidReading(pid=pid, value=None, error=str(exc))
        except (Elm327Error, TimeoutError, ValueError) as exc:
            return PidReading(pid=pid, value=None, error=str(exc))

    async def read_all_battery_pids(self, pids: list[PidDef] | None = None) -> list[PidReading]:
        pids = pids if pids is not None else BATTERY_PIDS
        readings = []
        for pid in pids:
            readings.append(await self.read_pid(pid))
        return readings


__all__ = [
    "IPaceSession",
    "PidReading",
    "DiscoveredAdapter",
    "scan_for_adapters",
    "scan_all",
]
