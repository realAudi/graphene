import pytest

from ipace_obd.uds import (
    NegativeResponseError,
    decode_dtc_status,
    decode_legacy_dtc,
    decode_legacy_dtc_list,
    decode_uds_dtc,
    decode_uds_dtc_list,
    extract_bytes,
    find_legacy_response,
    find_uds_response,
)


def test_extract_bytes_drops_header_token():
    # "7EC" is a 3-char header token and should be dropped; remaining are data bytes.
    assert extract_bytes("7EC 06 62 49 0F 0F A1") == [0x06, 0x62, 0x49, 0x0F, 0x0F, 0xA1]


def test_extract_bytes_multiple_lines():
    raw = "7EC 10 62 49 0F 0F A1\n7EC 21 00 00 00 00 00"
    assert extract_bytes(raw) == [0x10, 0x62, 0x49, 0x0F, 0x0F, 0xA1, 0x21, 0x00, 0x00, 0x00, 0x00, 0x00]


def test_find_uds_response_basic():
    raw = "7EC 06 62 49 0F 0F A1"
    payload = find_uds_response(raw, service=0x22, did=0x490F, did_len=2)
    assert payload == bytes([0x0F, 0xA1])


def test_find_uds_response_no_header():
    raw = "62 49 10 0F A1"
    payload = find_uds_response(raw, service=0x22, did=0x4910, did_len=2)
    assert payload == bytes([0x0F, 0xA1])


def test_find_uds_response_negative():
    raw = "7EC 03 7F 22 31"
    with pytest.raises(NegativeResponseError) as exc_info:
        find_uds_response(raw, service=0x22, did=0x4910, did_len=2)
    assert exc_info.value.nrc == 0x31


def test_find_uds_response_not_found():
    with pytest.raises(ValueError):
        find_uds_response("NO DATA", service=0x22, did=0x4910, did_len=2)


def test_find_legacy_response():
    raw = "7E8 06 43 02 01 33 02 44"
    payload = find_legacy_response(raw, mode=0x03)
    assert payload == bytes([0x02, 0x01, 0x33, 0x02, 0x44])


def test_decode_legacy_dtc_p_code():
    # P0301: category P (00), digit1 0, digit2 3 -> byte1 = 0b00_00_0011 = 0x03, byte2=0x01
    dtc = decode_legacy_dtc(0x03, 0x01)
    assert dtc.code == "P0301"


def test_decode_legacy_dtc_categories():
    assert decode_legacy_dtc(0b00000000, 0x00).code.startswith("P")
    assert decode_legacy_dtc(0b01000000, 0x00).code.startswith("C")
    assert decode_legacy_dtc(0b10000000, 0x00).code.startswith("B")
    assert decode_legacy_dtc(0b11000000, 0x00).code.startswith("U")


def test_decode_legacy_dtc_list_skips_padding():
    payload = bytes([0x03, 0x01, 0x00, 0x00, 0x01, 0x33])
    dtcs = decode_legacy_dtc_list(payload)
    codes = [d.code for d in dtcs]
    assert "P0301" in codes
    assert "P0133" in codes
    assert len(dtcs) == 2


def test_decode_legacy_dtc_list_with_count_prefix():
    # Odd-length payload => first byte treated as a count and dropped.
    payload = bytes([0x02, 0x03, 0x01, 0x01, 0x33])
    dtcs = decode_legacy_dtc_list(payload)
    codes = [d.code for d in dtcs]
    assert codes == ["P0301", "P0133"]


def test_decode_uds_dtc_includes_subtype_and_status():
    dtc = decode_uds_dtc(0x03, 0x01, 0x1A, 0x09)  # status bits 0 and 3 set
    assert dtc.code == "P0301-1A"
    assert dtc.subtype_byte == 0x1A
    assert dtc.status == 0x09


def test_decode_dtc_status_flags():
    flags = decode_dtc_status(0b00001001)  # bits 0 and 3
    assert "testFailed" in flags
    assert "confirmedDTC" in flags
    assert len(flags) == 2


def test_decode_uds_dtc_list():
    # Two records of 4 bytes each.
    payload = bytes([0x03, 0x01, 0x1A, 0x09, 0x40, 0x0A, 0x00, 0x08])
    dtcs = decode_uds_dtc_list(payload)
    assert len(dtcs) == 2
    assert dtcs[0].code == "P0301-1A"
    assert dtcs[1].code.startswith("C")
