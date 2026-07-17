import pytest

from ipace_obd.elm327 import Elm327, Elm327Error


class FakeTransport:
    def __init__(self, replies: dict[str, str]):
        self.replies = replies
        self.sent: list[str] = []

    async def send_raw(self, command: str) -> str:
        self.sent.append(command)
        return self.replies.get(command, "OK")


@pytest.mark.asyncio
async def test_initialize_sends_expected_sequence():
    transport = FakeTransport({"ATI": "ELM327 v1.5", "ATRV": "12.6V"})
    elm = Elm327(transport)
    info = await elm.initialize()
    assert info.id_string == "ELM327 v1.5"
    assert info.voltage == "12.6V"
    assert transport.sent[:6] == ["ATZ", "ATE0", "ATL0", "ATS0", "ATH1", "ATCAF1"]
    assert "ATSP0" in transport.sent


@pytest.mark.asyncio
async def test_set_header_only_sent_once_for_repeat_header():
    transport = FakeTransport({})
    elm = Elm327(transport)
    await elm.set_header("7E4")
    await elm.set_header("7E4")
    assert transport.sent.count("ATSH7E4") == 1


@pytest.mark.asyncio
async def test_set_header_sent_again_when_changed():
    transport = FakeTransport({})
    elm = Elm327(transport)
    await elm.set_header("7E4")
    await elm.set_header("7DF")
    assert transport.sent == ["ATSH7E4", "ATSH7DF"]


@pytest.mark.asyncio
async def test_request_does_not_raise_on_no_data():
    # request() uses allow_no_data=True since adapters legitimately report NO DATA for
    # unsupported PIDs - callers should check the reply text rather than catch an exception.
    transport = FakeTransport({"22490F": "NO DATA"})
    elm = Elm327(transport)
    reply = await elm.request("7E4", "22490F")
    assert "NO DATA" in reply


@pytest.mark.asyncio
async def test_initialize_raises_on_error_token():
    transport = FakeTransport({"ATZ": "ERROR"})
    elm = Elm327(transport)
    with pytest.raises(Elm327Error):
        await elm.initialize()
