from ipace_obd.pids.ipace_battery import BATTERY_PIDS, BATTERY_PIDS_BY_KEY


def test_all_pids_have_unique_keys():
    keys = [p.key for p in BATTERY_PIDS]
    assert len(keys) == len(set(keys))


def test_pid_lookup_by_key():
    assert BATTERY_PIDS_BY_KEY["soc_avg"].pid == 0x4910


def test_request_hex_format():
    pid = BATTERY_PIDS_BY_KEY["pack_voltage"]
    assert pid.request_hex == "22490F"


def test_soc_avg_decode():
    pid = BATTERY_PIDS_BY_KEY["soc_avg"]
    # 0x1D4C -> 7500 -> 75.00 %
    assert pid.decode(bytes([0x1D, 0x4C])) == 75.0


def test_pack_voltage_decode():
    pid = BATTERY_PIDS_BY_KEY["pack_voltage"]
    # 397.00 V -> 39700 -> 0x9B14
    assert round(pid.decode(bytes([0x9B, 0x14])), 2) == 397.00


def test_pack_current_offset_decode():
    pid = BATTERY_PIDS_BY_KEY["pack_current"]
    # Community formula is (A*256+B-32768)/40 - an offset-binary encoding (not two's
    # complement), where raw 32768 (0x8000) is the zero point.
    assert pid.decode(bytes([0x80, 0x00])) == 0.0
    raw = 32768 - 400  # -400 raw units below the zero point -> -10 A given /40 scale
    assert pid.decode(bytes([raw >> 8, raw & 0xFF])) == -10.0
    raw = 32768 + 400
    assert pid.decode(bytes([raw >> 8, raw & 0xFF])) == 10.0


def test_temp_decode():
    pid = BATTERY_PIDS_BY_KEY["temp_avg"]
    # byte value 80 -> 80/2 - 40 = 0 degC
    assert pid.decode(bytes([80])) == 0.0


def test_soh_decode():
    pid = BATTERY_PIDS_BY_KEY["soh_capacity_avg"]
    assert pid.decode(bytes([190])) == 95.0


def test_plate_temps_present():
    plate_keys = [p.key for p in BATTERY_PIDS if p.key.startswith("plate_temp_")]
    assert len(plate_keys) == 6
    pids = sorted(p.pid for p in BATTERY_PIDS if p.key.startswith("plate_temp_"))
    assert pids == list(range(0x492B, 0x4931))
