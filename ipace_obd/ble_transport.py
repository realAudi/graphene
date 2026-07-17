"""BLE transport for ELM327-based OBD-II dongles (e.g. Veepeak OBDCheck BLE).

These cheap dongles don't speak a "real" Bluetooth SPP serial profile - they expose a
GATT service with one characteristic you write ASCII ELM327 AT-commands/PID requests to,
and another characteristic that notifies you with the ASCII response. There is no single
universal UUID across every clone chipset, so we auto-detect:

  * Veepeak / generic "OBD-M" boards commonly expose service ``FFF0`` with characteristics
    ``FFF1``/``FFF2`` (one write, one notify - which is which varies by firmware batch).
  * Some ISSC/CC254x based clones expose the custom service
    ``49535343-fe7d-4ae5-8fa9-9fafd205e455`` with characteristics ``49535343-1e4d-...`` etc.
  * As a last resort we scan every service/characteristic on the device and pick the first
    pair that has (write or write-without-response) + notify properties.

Rather than hardcode which UUID is "TX" vs "RX", we inspect the GATT characteristic
*properties* reported by the adapter, which is far more reliable in practice.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice

logger = logging.getLogger(__name__)

# Known "OBD-ish" service UUIDs to prefer, in priority order.
_PREFERRED_SERVICES = [
    "0000fff0-0000-1000-8000-00805f9b34fb",  # FFF0 - most Veepeak / generic ELM327 BLE clones
    "49535343-fe7d-4ae5-8fa9-9fafd205e455",  # ISSC/CC254x based clones
]

_PROMPT = b">"
_DEFAULT_NAME_HINTS = ("veepeak", "obd", "elm327", "obdii", "obdcheck", "vlinker", "ovms")


@dataclass
class DiscoveredAdapter:
    device: BLEDevice
    name: str
    address: str
    rssi: Optional[int] = None


async def scan_for_adapters(timeout: float = 8.0) -> list[DiscoveredAdapter]:
    """Scan for nearby BLE devices that look like OBD-II adapters.

    Returns every device whose advertised name contains one of the common OBD dongle
    name hints (case-insensitive). If nothing matches, returns an empty list so callers
    can fall back to listing *all* BLE devices for the user to pick from manually.
    """
    found: list[DiscoveredAdapter] = []
    devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
    for device, adv in devices.values():
        name = (device.name or adv.local_name or "").strip()
        if not name:
            continue
        lname = name.lower()
        if any(hint in lname for hint in _DEFAULT_NAME_HINTS):
            found.append(DiscoveredAdapter(device=device, name=name, address=device.address, rssi=adv.rssi))
    return found


async def scan_all(timeout: float = 8.0) -> list[DiscoveredAdapter]:
    """Scan for *every* nearby BLE device (for manual selection when auto-detect fails)."""
    devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
    out = []
    for device, adv in devices.values():
        name = device.name or adv.local_name or "(unnamed)"
        out.append(DiscoveredAdapter(device=device, name=name, address=device.address, rssi=adv.rssi))
    return out


class Elm327BleTransport:
    """Async transport that speaks the ELM327 ASCII protocol over a BLE GATT UART bridge."""

    def __init__(self, address_or_device, response_timeout: float = 5.0):
        self._address_or_device = address_or_device
        self._client: Optional[BleakClient] = None
        self._write_char = None
        self._write_mode_response_required = False
        self._notify_char = None
        self._rx_buffer = bytearray()
        self._rx_event = asyncio.Event()
        self._response_timeout = response_timeout
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        self._client = BleakClient(self._address_or_device)
        await self._client.connect()
        logger.info("Connected to %s", self._client.address)

        write_char, notify_char, write_needs_response = self._find_characteristics()
        if write_char is None or notify_char is None:
            await self._client.disconnect()
            raise RuntimeError(
                "Could not find a writable + notifiable GATT characteristic pair on this "
                "device. It may not be an ELM327-compatible BLE adapter, or uses an "
                "unsupported chipset."
            )
        self._write_char = write_char
        self._write_mode_response_required = write_needs_response
        self._notify_char = notify_char

        await self._client.start_notify(notify_char, self._on_notify)
        logger.info(
            "Using characteristics write=%s notify=%s (service coverage complete)",
            write_char.uuid,
            notify_char.uuid,
        )

    def _find_characteristics(self):
        assert self._client is not None
        services = self._client.services

        def pick_from(service_uuids):
            for svc in services:
                if svc.uuid.lower() not in service_uuids:
                    continue
                write_char = None
                notify_char = None
                needs_response = False
                for char in svc.characteristics:
                    props = set(char.properties)
                    if notify_char is None and ("notify" in props or "indicate" in props):
                        notify_char = char
                    if write_char is None and ("write" in props or "write-without-response" in props):
                        write_char = char
                        needs_response = "write" in props and "write-without-response" not in props
                if write_char and notify_char:
                    return write_char, notify_char, needs_response
            return None, None, False

        preferred = {u.lower() for u in _PREFERRED_SERVICES}
        w, n, r = pick_from(preferred)
        if w and n:
            return w, n, r

        # Fallback: scan every service for a write+notify pair.
        all_uuids = {svc.uuid.lower() for svc in services}
        return pick_from(all_uuids)

    def _on_notify(self, _handle, data: bytearray) -> None:
        self._rx_buffer.extend(data)
        if _PROMPT in self._rx_buffer:
            self._rx_event.set()

    async def disconnect(self) -> None:
        if self._client and self._client.is_connected:
            try:
                if self._notify_char is not None:
                    await self._client.stop_notify(self._notify_char)
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass
            await self._client.disconnect()

    async def __aenter__(self) -> "Elm327BleTransport":
        await self.connect()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.disconnect()

    async def send_raw(self, command: str) -> str:
        """Send a raw ELM327 command (AT command or PID request) and return the decoded reply.

        The trailing ELM327 ``>`` prompt is stripped. Multiple response lines are joined
        with ``\\n``.
        """
        if self._client is None or self._write_char is None:
            raise RuntimeError("Not connected - call connect() first")

        async with self._lock:
            self._rx_buffer.clear()
            self._rx_event.clear()
            payload = (command.strip() + "\r").encode("ascii")
            await self._client.write_gatt_char(
                self._write_char, payload, response=self._write_mode_response_required
            )
            try:
                await asyncio.wait_for(self._rx_event.wait(), timeout=self._response_timeout)
            except asyncio.TimeoutError as exc:
                raise TimeoutError(
                    f"No response from OBD adapter within {self._response_timeout}s "
                    f"for command {command!r}"
                ) from exc

            raw = bytes(self._rx_buffer)
            text = raw.decode("ascii", errors="ignore")
            text = text.replace(">", "")
            # Echo of the command itself may be present if ATE0 hasn't taken effect yet.
            lines = [ln.strip() for ln in text.replace("\r", "\n").split("\n")]
            lines = [ln for ln in lines if ln]
            return "\n".join(lines)

    @property
    def is_connected(self) -> bool:
        return bool(self._client and self._client.is_connected)
