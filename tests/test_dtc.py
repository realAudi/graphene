import pytest

from ipace_obd.dtc import BROADCAST_HEADER, clear_legacy_dtcs, read_legacy_dtcs
from ipace_obd.elm327 import Elm327


class FakeTransport:
    """Minimal fake transport that records sent commands and returns canned replies."""

    def __init__(self, replies: dict[str, str]):
        self.replies = replies
        self.sent: list[str] = []

    async def send_raw(self, command: str) -> str:
        self.sent.append(command)
        return self.replies.get(command, "NO DATA")


@pytest.mark.asyncio
async def test_read_legacy_dtcs_parses_response():
    transport = FakeTransport(
        {
            "ATSH7DF": "OK",
            "03": "7E8 06 43 02 03 01 01 33",
        }
    )
    elm = Elm327(transport)
    dtcs = await read_legacy_dtcs(elm, "stored")
    codes = [d.code for d in dtcs]
    assert "P0301" in codes
    assert "P0133" in codes


@pytest.mark.asyncio
async def test_read_legacy_dtcs_no_codes():
    transport = FakeTransport(
        {
            "ATSH7DF": "OK",
            "03": "7E8 02 43 00",
        }
    )
    elm = Elm327(transport)
    dtcs = await read_legacy_dtcs(elm, "stored")
    assert dtcs == []


@pytest.mark.asyncio
async def test_clear_legacy_dtcs_sends_mode_04_to_broadcast():
    transport = FakeTransport({"ATSH7DF": "OK", "04": "44"})
    elm = Elm327(transport)
    reply = await clear_legacy_dtcs(elm)
    assert reply == "44"
    assert f"ATSH{BROADCAST_HEADER}" in transport.sent
    assert "04" in transport.sent
