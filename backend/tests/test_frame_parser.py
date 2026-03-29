import pytest
from modbus.frame_parser import (
    parse_tcp_frame,
    MBAPHeader,
    ParsedFrame,
    EXCEPTION_NAMES,
    FC_NAMES,
)


# ── helpers ──────────────────────────────────────────────────────────────────

TS = 1_700_000_000_000_000  # fixed µs timestamp for all tests

# FC3 Read Holding Registers request: TID=1, UID=1, start=0x006C, count=10
TCP_FC3_REQ = bytes([
    0x00, 0x01,  # TID
    0x00, 0x00,  # PID
    0x00, 0x06,  # LEN = 6
    0x01,        # Unit ID
    0x03,        # FC3
    0x00, 0x6C,  # start address = 108
    0x00, 0x0A,  # count = 10
])

# FC3 response: 4 registers (8 bytes data)
TCP_FC3_RESP = bytes([
    0x00, 0x01,  # TID
    0x00, 0x00,  # PID
    0x00, 0x0B,  # LEN = 11
    0x01,        # Unit ID
    0x03,        # FC3
    0x08,        # byte count = 8
    0x00, 0x64, 0x01, 0x2C, 0x00, 0x00, 0xFF, 0xFF,  # 4 registers
])

# FC3 exception response (EC 0x02 = Illegal Data Address)
TCP_FC3_EXC = bytes([
    0x00, 0x01,  # TID
    0x00, 0x00,  # PID
    0x00, 0x03,  # LEN = 3
    0x01,        # Unit ID
    0x83,        # FC3 | 0x80
    0x02,        # exception code
])

# Truncated frame (only MBAP header, no PDU)
TCP_TRUNCATED = bytes([0x00, 0x01, 0x00, 0x00, 0x00, 0x06, 0x01])

# Wrong protocol ID
TCP_BAD_PID = bytes([
    0x00, 0x01, 0x00, 0x01, 0x00, 0x06,
    0x01, 0x03, 0x00, 0x00, 0x00, 0x01,
])


# ── TCP tests ─────────────────────────────────────────────────────────────────

def test_parse_tcp_fc3_request_mbap():
    f = parse_tcp_frame(TCP_FC3_REQ, "tx", TS)
    assert f.mbap is not None
    assert f.mbap.transaction_id == 1
    assert f.mbap.protocol_id == 0
    assert f.mbap.length == 6
    assert f.mbap.unit_id == 1


def test_parse_tcp_fc3_request_pdu():
    f = parse_tcp_frame(TCP_FC3_REQ, "tx", TS)
    assert f.function_code == 3
    assert f.fc_name == "Read Holding Registers"
    assert f.is_exception is False
    assert f.exception_code is None
    assert f.start_address == 0x6C
    assert f.quantity == 10
    assert f.crc_valid is None
    assert f.parse_error is None


def test_parse_tcp_fc3_response():
    f = parse_tcp_frame(TCP_FC3_RESP, "rx", TS)
    assert f.function_code == 3
    assert f.is_exception is False
    assert f.byte_count == 8
    assert f.data_hex is not None
    assert len(f.data_hex) == 16  # 8 bytes → 16 hex chars (no spaces)
    assert f.parse_error is None


def test_parse_tcp_exception_response():
    f = parse_tcp_frame(TCP_FC3_EXC, "rx", TS)
    assert f.is_exception is True
    assert f.function_code == 3        # stripped high bit
    assert f.exception_code == 0x02
    assert f.exception_name == "Illegal Data Address"
    assert f.parse_error is None


def test_parse_tcp_truncated_frame():
    f = parse_tcp_frame(TCP_TRUNCATED, "tx", TS)
    assert f.parse_error is not None
    assert "truncated" in f.parse_error.lower()


def test_parse_tcp_bad_protocol_id():
    f = parse_tcp_frame(TCP_BAD_PID, "tx", TS)
    assert f.parse_error is not None
    assert "protocol" in f.parse_error.lower()


def test_parse_tcp_direction_and_timestamp():
    f = parse_tcp_frame(TCP_FC3_REQ, "tx", TS)
    assert f.direction == "tx"
    assert f.ts_us == TS
    assert f.frame_type == "tcp"


def test_parse_tcp_raw_hex_is_full_frame():
    f = parse_tcp_frame(TCP_FC3_REQ, "tx", TS)
    assert f.raw_hex == TCP_FC3_REQ.hex()


def test_exception_names_table():
    assert EXCEPTION_NAMES[0x01] == "Illegal Function"
    assert EXCEPTION_NAMES[0x02] == "Illegal Data Address"
    assert EXCEPTION_NAMES[0x0B] == "Gateway Target Device Failed to Respond"


def test_fc_names_table():
    assert FC_NAMES[1] == "Read Coils"
    assert FC_NAMES[3] == "Read Holding Registers"
    assert FC_NAMES[16] == "Write Multiple Registers"
    assert "Unknown" in FC_NAMES.get(99, "FC99 (Unknown)")


def test_unknown_fc_name():
    raw = bytes([0x00, 0x01, 0x00, 0x00, 0x00, 0x04, 0x01, 0x63, 0x00, 0x01])
    f = parse_tcp_frame(raw, "tx", TS)
    assert "Unknown" in f.fc_name or f.fc_name.startswith("FC")


def test_parse_tcp_truncated_response_data():
    """byte_count claims 10 bytes but frame only has 2."""
    raw = bytes([
        0x00, 0x01, 0x00, 0x00, 0x00, 0x07,  # LEN = 7
        0x01,        # Unit ID
        0x03,        # FC3
        0x0A,        # byte_count = 10
        0x00, 0x01,  # only 2 bytes of data (truncated)
    ])
    f = parse_tcp_frame(raw, "rx", TS)
    assert f.parse_error is not None
    assert "truncated" in f.parse_error.lower()
    assert f.data_hex is None   # must not return partial data
    assert f.byte_count == 10


from modbus.frame_parser import parse_rtu_frame


# ── RTU helpers ───────────────────────────────────────────────────────────────

def _crc16(data: bytes) -> bytes:
    """CRC-16/IBM — returns 2 bytes little-endian."""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def _rtu(body: bytes) -> bytes:
    """Append a valid CRC to a RTU frame body."""
    return body + _crc16(body)


# FC3 request: UID=1, FC=3, start=0, count=2
RTU_FC3_REQ = _rtu(bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x02]))

# FC3 response: UID=1, FC=3, 4 bytes data (2 regs)
RTU_FC3_RESP = _rtu(bytes([0x01, 0x03, 0x04, 0x00, 0x64, 0x01, 0x2C]))

# FC3 exception: UID=1, FC=0x83, EC=0x02
RTU_FC3_EXC = _rtu(bytes([0x01, 0x83, 0x02]))

# Bad CRC: valid body but wrong CRC bytes
RTU_BAD_CRC = _rtu(bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x02]))[:-2] + bytes([0xDE, 0xAD])


# ── RTU tests ─────────────────────────────────────────────────────────────────

def test_parse_rtu_fc3_request():
    f = parse_rtu_frame(RTU_FC3_REQ, "tx", TS)
    assert f.function_code == 3
    assert f.fc_name == "Read Holding Registers"
    assert f.start_address == 0
    assert f.quantity == 2
    assert f.crc_valid is True
    assert f.is_exception is False
    assert f.frame_type == "rtu"
    assert f.mbap is None
    assert f.parse_error is None


def test_parse_rtu_fc3_response():
    f = parse_rtu_frame(RTU_FC3_RESP, "rx", TS)
    assert f.function_code == 3
    assert f.byte_count == 4
    assert f.data_hex == "0064012c"
    assert f.crc_valid is True
    assert f.parse_error is None


def test_parse_rtu_exception():
    f = parse_rtu_frame(RTU_FC3_EXC, "rx", TS)
    assert f.is_exception is True
    assert f.function_code == 3
    assert f.exception_code == 0x02
    assert f.exception_name == "Illegal Data Address"
    assert f.crc_valid is True


def test_parse_rtu_bad_crc():
    f = parse_rtu_frame(RTU_BAD_CRC, "tx", TS)
    assert f.crc_valid is False
    assert f.parse_error is not None
    assert "crc" in f.parse_error.lower()


def test_parse_rtu_truncated():
    f = parse_rtu_frame(bytes([0x01]), "tx", TS)
    assert f.parse_error is not None
    assert "truncated" in f.parse_error.lower()


def test_parse_rtu_raw_hex_includes_crc():
    f = parse_rtu_frame(RTU_FC3_REQ, "tx", TS)
    assert f.raw_hex == RTU_FC3_REQ.hex()
