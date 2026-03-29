"""
Predefined Modbus register maps for common ICS/OT device types.

Each entry is a list of RegisterDef namedtuples:
  address   : Modbus register address (0-based, holding registers unless noted)
  name      : Human-readable field name
  unit      : Engineering unit string (e.g. "V", "A", "W", "°C")
  scale     : Divide raw register value by this to get engineering value
  data_type : "uint16" | "int16" | "uint32" | "int32" | "float32"
               (32-bit types occupy 2 consecutive registers)
  access    : "ro" read-only | "rw" read-write | "wo" write-only
  min_val   : Simulated minimum (for realistic random generation)
  max_val   : Simulated maximum

DEVICE_TYPES maps lower-cased keyword → list[RegisterDef]
Keywords are matched against device_type and device_name columns in the
uploaded CSV/Excel file (substring match, case-insensitive).

HOW MATCHING WORKS
------------------
  device_type or device_name column value → lower-cased → keyword search
  e.g. "SMA Tripower 25000TL" → matches "sma" → SMA_SUNNY_BOY map
       "Fronius Symo 15.0-3" → matches "fronius" → FRONIUS_SYMO map
       "ABB REACT2" → matches "abb" → ABB_REACT2 map
       "kW meter" → matches "meter" → GENERIC_ENERGY_METER map
       "PLC" → matches "plc" → GENERIC_PLC map
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class RegisterDef:
    address:   int
    name:      str
    unit:      str
    scale:     float
    data_type: Literal[
        "uint16", "int16", "uint32", "int32", "float32",
        "float64", "int64", "uint64", "string", "boolean", "bcd",
    ] = "uint16"
    access:    Literal["ro", "rw", "wo"] = "ro"
    min_val:   float = 0.0
    max_val:   float = 65535.0
    description: str = ""
    # Extended fields (all optional — backward compatible)
    register_type: Literal["holding", "input", "coil", "discrete"] = "holding"
    byte_order:    Literal["ABCD", "BADC", "CDAB", "DCBA"] | None = None  # None = inherit from session
    string_length: int = 0             # for data_type="string": number of chars (2 per register)
    bit_position:  int = 0             # for data_type="boolean": which bit 0-15 to extract


# ── Solar Inverters ───────────────────────────────────────────────────────────

SMA_SUNNY_BOY: list[RegisterDef] = [
    RegisterDef(30051, "DC Power",            "W",   1.0,  "int32",  "ro", 0,    25000, "Total DC input power"),
    RegisterDef(30053, "AC Power",            "W",   1.0,  "int32",  "ro", 0,    25000, "Total AC output power"),
    RegisterDef(30057, "AC Grid Freq",        "Hz",  100.0,"int32",  "ro", 4900, 5100,  "Grid frequency ×100"),
    RegisterDef(30769, "DC Voltage (A)",      "V",   100.0,"int32",  "ro", 30000,85000, "String A DC voltage ×100"),
    RegisterDef(30771, "DC Current (A)",      "A",   1000.0,"int32", "ro", 0,    40000, "String A DC current ×1000"),
    RegisterDef(30775, "AC Voltage (Ph A)",   "V",   100.0,"int32",  "ro", 22000,24400, "Phase A AC voltage ×100"),
    RegisterDef(30777, "AC Current (Ph A)",   "A",   1000.0,"int32", "ro", 0,    40000, "Phase A AC current ×1000"),
    RegisterDef(30803, "Total Yield",         "kWh", 1000.0,"uint32","ro", 0,    9999999,"Total energy produced ×1000"),
    RegisterDef(30835, "Cabinet Temp",        "°C",  10.0, "int32",  "ro", 200,  700,   "Internal temperature ×10"),
    RegisterDef(30869, "Operating Status",    "",    1.0,  "uint32", "ro", 307,  307,   "Enum: 307=MPP, 16777213=Error"),
    RegisterDef(30953, "Grid Contact Status", "",    1.0,  "uint32", "ro", 51,   51,    "Enum: 51=Closed"),
    RegisterDef(40009, "Max Active Power",    "W",   1.0,  "uint32", "rw", 0,    25000, "Active power limit"),
    RegisterDef(40015, "Cos Phi",             "",    1000.0,"int32", "rw", -1000,1000,  "Power factor setpoint ×1000"),
]

FRONIUS_SYMO: list[RegisterDef] = [
    RegisterDef(40070, "AC Power",            "W",   1.0,  "int16",  "ro", 0,    25000, "AC output power"),
    RegisterDef(40072, "AC Energy Today",     "Wh",  1.0,  "uint32", "ro", 0,    99999, "Energy today"),
    RegisterDef(40076, "AC Voltage (A-N)",    "V",   10.0, "uint16", "ro", 2200, 2400,  "Phase A voltage ×10"),
    RegisterDef(40077, "AC Voltage (B-N)",    "V",   10.0, "uint16", "ro", 2200, 2400,  "Phase B voltage ×10"),
    RegisterDef(40078, "AC Voltage (C-N)",    "V",   10.0, "uint16", "ro", 2200, 2400,  "Phase C voltage ×10"),
    RegisterDef(40079, "AC Current (A)",      "A",   10.0, "int16",  "ro", 0,    1000,  "Phase A current ×10"),
    RegisterDef(40080, "AC Current (B)",      "A",   10.0, "int16",  "ro", 0,    1000,  "Phase B current ×10"),
    RegisterDef(40081, "AC Current (C)",      "A",   10.0, "int16",  "ro", 0,    1000,  "Phase C current ×10"),
    RegisterDef(40083, "AC Freq",             "Hz",  100.0,"uint16", "ro", 4990, 5010,  "Grid freq ×100"),
    RegisterDef(40084, "AC Apparent Power",   "VA",  1.0,  "int16",  "ro", 0,    27500, "Apparent power"),
    RegisterDef(40086, "AC Reactive Power",   "VAr", 1.0,  "int16",  "ro", -5000,5000,  "Reactive power"),
    RegisterDef(40087, "AC Power Factor",     "",    100.0,"int16",  "ro", -100, 100,   "Power factor ×100"),
    RegisterDef(40094, "DC Power (1)",        "W",   1.0,  "int16",  "ro", 0,    15000, "MPPT1 DC power"),
    RegisterDef(40096, "DC Voltage (1)",      "V",   10.0, "uint16", "ro", 2000, 9000,  "MPPT1 voltage ×10"),
    RegisterDef(40097, "DC Current (1)",      "A",   10.0, "int16",  "ro", 0,    2500,  "MPPT1 current ×10"),
    RegisterDef(40108, "Temp Heatsink",       "°C",  10.0, "int16",  "ro", 200,  800,   "Heatsink temp ×10"),
    RegisterDef(40110, "Inverter Status",     "",    1.0,  "uint16", "ro", 4,    4,     "Status enum: 4=MPPT"),
    RegisterDef(40230, "Active Power Limit",  "%",   10.0, "uint16", "rw", 0,    1000,  "Power limit setpoint ×10"),
]

ABB_REACT2: list[RegisterDef] = [
    RegisterDef(10100, "DC Voltage",          "V",   10.0, "uint16", "ro", 3000, 9000,  "DC voltage ×10"),
    RegisterDef(10101, "DC Current",          "A",   10.0, "uint16", "ro", 0,    3000,  "DC current ×10"),
    RegisterDef(10102, "DC Power",            "W",   1.0,  "uint16", "ro", 0,    10000, "DC power"),
    RegisterDef(10103, "AC Power",            "W",   1.0,  "int16",  "ro", 0,    10000, "AC power"),
    RegisterDef(10104, "AC Freq",             "Hz",  100.0,"uint16", "ro", 4990, 5010,  "Frequency ×100"),
    RegisterDef(10105, "AC Voltage L1",       "V",   10.0, "uint16", "ro", 2200, 2400,  "L1 voltage ×10"),
    RegisterDef(10106, "AC Voltage L2",       "V",   10.0, "uint16", "ro", 2200, 2400,  "L2 voltage ×10"),
    RegisterDef(10107, "AC Voltage L3",       "V",   10.0, "uint16", "ro", 2200, 2400,  "L3 voltage ×10"),
    RegisterDef(10108, "AC Current L1",       "A",   10.0, "int16",  "ro", 0,    500,   "L1 current ×10"),
    RegisterDef(10109, "AC Current L2",       "A",   10.0, "int16",  "ro", 0,    500,   "L2 current ×10"),
    RegisterDef(10110, "AC Current L3",       "A",   10.0, "int16",  "ro", 0,    500,   "L3 current ×10"),
    RegisterDef(10111, "Total Energy",        "kWh", 10.0, "uint32", "ro", 0,    9999999,"Lifetime energy ×10"),
    RegisterDef(10200, "Alarm Code",          "",    1.0,  "uint16", "ro", 0,    0,     "0=No alarm"),
    RegisterDef(10300, "Power Setpoint",      "W",   1.0,  "uint16", "rw", 0,    10000, "Active power setpoint"),
]

SOLAREDGE_SE: list[RegisterDef] = [
    RegisterDef(40069, "AC Power",            "W",   1.0,  "int16",  "ro", 0,    17000, "AC output power"),
    RegisterDef(40072, "AC Energy (life)",    "Wh",  1.0,  "uint32", "ro", 0,    99999999,"Lifetime energy"),
    RegisterDef(40076, "AC Voltage A-N",      "V",   100.0,"uint16", "ro", 21000,24000,  "Phase A voltage ×100"),
    RegisterDef(40079, "AC Current",          "A",   100.0,"int16",  "ro", 0,    2500,  "AC current ×100"),
    RegisterDef(40083, "AC Frequency",        "Hz",  100.0,"uint16", "ro", 4990, 5010,  "Frequency ×100"),
    RegisterDef(40087, "Reactive Power",      "VAr", 1.0,  "int16",  "ro", -5000,5000,  "Reactive power"),
    RegisterDef(40088, "Power Factor",        "",    100.0,"int16",  "ro", -100, 100,   "PF ×100"),
    RegisterDef(40095, "DC Voltage",          "V",   100.0,"int16",  "ro", 25000,85000, "DC voltage ×100"),
    RegisterDef(40096, "DC Current",          "A",   100.0,"int16",  "ro", 0,    5000,  "DC current ×100"),
    RegisterDef(40097, "DC Power",            "W",   1.0,  "int16",  "ro", 0,    17000, "DC power"),
    RegisterDef(40107, "Temp Heatsink",       "°C",  100.0,"int16",  "ro", 2000, 7500,  "Heatsink ×100"),
    RegisterDef(40108, "Status",              "",    1.0,  "uint16", "ro", 4,    4,     "4=MPPT"),
    RegisterDef(44000, "Power Limit",         "%",   1.0,  "uint16", "rw", 0,    100,   "Pmax setpoint %"),
]

GROWATT_SPH: list[RegisterDef] = [
    RegisterDef(1,  "Status",                 "",    1.0,  "uint16", "ro", 1,    1,     "0=Stand-by,1=Normal"),
    RegisterDef(3,  "Input Power High",       "W",   10.0, "uint16", "ro", 0,    65535, "PV power high word ×10"),
    RegisterDef(4,  "Input Power Low",        "W",   10.0, "uint16", "ro", 0,    65535, "PV power low word ×10"),
    RegisterDef(5,  "PV1 Voltage",            "V",   10.0, "uint16", "ro", 0,    9000,  "PV1 voltage ×10"),
    RegisterDef(6,  "PV1 Current",            "A",   10.0, "uint16", "ro", 0,    3000,  "PV1 current ×10"),
    RegisterDef(7,  "PV1 Power High",         "W",   10.0, "uint16", "ro", 0,    65535, "PV1 power high"),
    RegisterDef(35, "Output Power High",      "W",   10.0, "uint16", "ro", 0,    65535, "AC output high word ×10"),
    RegisterDef(36, "Output Power Low",       "W",   10.0, "uint16", "ro", 0,    65535, "AC output low word ×10"),
    RegisterDef(38, "Grid Freq",              "Hz",  100.0,"uint16", "ro", 4990, 5010,  "Grid frequency ×100"),
    RegisterDef(39, "AC Voltage L1",          "V",   10.0, "uint16", "ro", 2200, 2400,  "L1 voltage ×10"),
    RegisterDef(40, "AC Current L1",          "A",   10.0, "uint16", "ro", 0,    1000,  "L1 current ×10"),
    RegisterDef(55, "Total Energy High",      "kWh", 10.0, "uint16", "ro", 0,    65535, "Total yield high"),
    RegisterDef(56, "Total Energy Low",       "kWh", 10.0, "uint16", "ro", 0,    65535, "Total yield low"),
    RegisterDef(93, "Inner Temp",             "°C",  10.0, "int16",  "ro", 200,  800,   "Internal temperature ×10"),
]

# ── Energy Meters ─────────────────────────────────────────────────────────────

GENERIC_ENERGY_METER: list[RegisterDef] = [
    RegisterDef(0,   "Voltage L1-N",          "V",   10.0, "uint16", "ro", 2150, 2450,  "Phase 1 voltage ×10"),
    RegisterDef(1,   "Voltage L2-N",          "V",   10.0, "uint16", "ro", 2150, 2450,  "Phase 2 voltage ×10"),
    RegisterDef(2,   "Voltage L3-N",          "V",   10.0, "uint16", "ro", 2150, 2450,  "Phase 3 voltage ×10"),
    RegisterDef(3,   "Current L1",            "A",   100.0,"int16",  "ro", -10000,10000,"Phase 1 current ×100"),
    RegisterDef(4,   "Current L2",            "A",   100.0,"int16",  "ro", -10000,10000,"Phase 2 current ×100"),
    RegisterDef(5,   "Current L3",            "A",   100.0,"int16",  "ro", -10000,10000,"Phase 3 current ×100"),
    RegisterDef(6,   "Active Power Total",    "kW",  1000.0,"int32", "ro", -50000,50000,"Total active power ×1000"),
    RegisterDef(8,   "Reactive Power Total",  "kVAr",1000.0,"int32","ro", -20000,20000,"Total reactive power ×1000"),
    RegisterDef(10,  "Apparent Power Total",  "kVA", 1000.0,"uint32","ro", 0,    50000, "Total apparent power ×1000"),
    RegisterDef(12,  "Power Factor",          "",    1000.0,"int16", "ro", -1000,1000,  "PF ×1000"),
    RegisterDef(13,  "Frequency",             "Hz",  100.0,"uint16", "ro", 4990, 5010,  "Grid frequency ×100"),
    RegisterDef(14,  "Import Energy",         "kWh", 100.0,"uint32", "ro", 0,    9999999,"Import active energy ×100"),
    RegisterDef(16,  "Export Energy",         "kWh", 100.0,"uint32", "ro", 0,    9999999,"Export active energy ×100"),
    RegisterDef(18,  "Voltage L1-L2",         "V",   10.0, "uint16", "ro", 3700, 4200,  "L1-L2 line voltage ×10"),
    RegisterDef(19,  "Voltage L2-L3",         "V",   10.0, "uint16", "ro", 3700, 4200,  "L2-L3 line voltage ×10"),
    RegisterDef(20,  "Voltage L3-L1",         "V",   10.0, "uint16", "ro", 3700, 4200,  "L3-L1 line voltage ×10"),
]

CARLO_GAVAZZI_EM: list[RegisterDef] = [
    RegisterDef(0,   "V L1",                  "V",   10.0, "int32",  "ro", 2150, 2450,  "L1 voltage ×10"),
    RegisterDef(2,   "V L2",                  "V",   10.0, "int32",  "ro", 2150, 2450,  "L2 voltage ×10"),
    RegisterDef(4,   "V L3",                  "V",   10.0, "int32",  "ro", 2150, 2450,  "L3 voltage ×10"),
    RegisterDef(12,  "A L1",                  "A",   1000.0,"int32", "ro", -5000,5000,  "L1 current ×1000"),
    RegisterDef(14,  "A L2",                  "A",   1000.0,"int32", "ro", -5000,5000,  "L2 current ×1000"),
    RegisterDef(16,  "A L3",                  "A",   1000.0,"int32", "ro", -5000,5000,  "L3 current ×1000"),
    RegisterDef(28,  "W Total",               "W",   10.0, "int32",  "ro", -50000,50000,"Total active power ×10"),
    RegisterDef(50,  "PF Total",              "",    1000.0,"int16", "ro", -1000,1000,  "Power factor ×1000"),
    RegisterDef(52,  "Hz",                    "Hz",  10.0, "uint16", "ro", 499,  501,   "Frequency ×10"),
    RegisterDef(60,  "kWh Import (3P)",       "kWh", 10.0, "uint32", "ro", 0,    9999999,"Total import ×10"),
    RegisterDef(78,  "kWh Export (3P)",       "kWh", 10.0, "uint32", "ro", 0,    9999999,"Total export ×10"),
]

# ── Battery Storage ───────────────────────────────────────────────────────────

BYD_HVM: list[RegisterDef] = [
    RegisterDef(500, "Battery Voltage",       "V",   10.0, "uint16", "ro", 4000, 5800,  "Pack voltage ×10"),
    RegisterDef(501, "Battery Current",       "A",   10.0, "int16",  "ro", -2000,2000,  "Pack current ×10 (+ charge)"),
    RegisterDef(502, "Battery Power",         "W",   1.0,  "int16",  "ro", -10000,10000,"Pack power"),
    RegisterDef(503, "State of Charge",       "%",   1.0,  "uint16", "ro", 0,    100,   "SOC percent"),
    RegisterDef(504, "State of Health",       "%",   1.0,  "uint16", "ro", 80,   100,   "SOH percent"),
    RegisterDef(505, "Cell Temp Max",         "°C",  10.0, "int16",  "ro", 150,  450,   "Max cell temp ×10"),
    RegisterDef(506, "Cell Temp Min",         "°C",  10.0, "int16",  "ro", 100,  350,   "Min cell temp ×10"),
    RegisterDef(507, "Cell Voltage Max",      "mV",  1.0,  "uint16", "ro", 3300, 3700,  "Max cell voltage"),
    RegisterDef(508, "Cell Voltage Min",      "mV",  1.0,  "uint16", "ro", 3200, 3600,  "Min cell voltage"),
    RegisterDef(509, "Charge Cycles",         "",    1.0,  "uint16", "ro", 0,    5000,  "Full charge cycles"),
    RegisterDef(510, "Total Discharged",      "kWh", 10.0, "uint32", "ro", 0,    999999,"Total discharge energy ×10"),
    RegisterDef(520, "Alarm Status",          "",    1.0,  "uint16", "ro", 0,    0,     "0=No alarm"),
    RegisterDef(600, "Max Charge Power",      "W",   1.0,  "uint16", "rw", 0,    10000, "Charge power limit setpoint"),
    RegisterDef(601, "Max Discharge Power",   "W",   1.0,  "uint16", "rw", 0,    10000, "Discharge power limit setpoint"),
    RegisterDef(602, "SOC Min Limit",         "%",   1.0,  "uint16", "rw", 0,    100,   "Minimum SOC setpoint"),
    RegisterDef(603, "SOC Max Limit",         "%",   1.0,  "uint16", "rw", 0,    100,   "Maximum SOC setpoint"),
]

# ── Generic PLC / RTU ─────────────────────────────────────────────────────────

GENERIC_PLC: list[RegisterDef] = [
    RegisterDef(0,   "DI Status Word",        "",    1.0,  "uint16", "ro", 0,    65535, "Digital input bitmask"),
    RegisterDef(1,   "DO Status Word",        "",    1.0,  "uint16", "rw", 0,    65535, "Digital output bitmask"),
    RegisterDef(2,   "AI Channel 0",          "raw", 1.0,  "uint16", "ro", 0,    32767, "Analog input 0 (0-32767)"),
    RegisterDef(3,   "AI Channel 1",          "raw", 1.0,  "uint16", "ro", 0,    32767, "Analog input 1"),
    RegisterDef(4,   "AI Channel 2",          "raw", 1.0,  "uint16", "ro", 0,    32767, "Analog input 2"),
    RegisterDef(5,   "AI Channel 3",          "raw", 1.0,  "uint16", "ro", 0,    32767, "Analog input 3"),
    RegisterDef(6,   "AO Channel 0",          "raw", 1.0,  "uint16", "rw", 0,    32767, "Analog output 0"),
    RegisterDef(7,   "AO Channel 1",          "raw", 1.0,  "uint16", "rw", 0,    32767, "Analog output 1"),
    RegisterDef(10,  "Counter 0",             "cnt", 1.0,  "uint32", "ro", 0,    4294967295,"Event counter 0"),
    RegisterDef(12,  "Counter 1",             "cnt", 1.0,  "uint32", "ro", 0,    4294967295,"Event counter 1"),
    RegisterDef(20,  "Temperature 0",         "°C",  10.0, "int16",  "ro", -200, 1500,  "RTD/TC channel 0 ×10"),
    RegisterDef(21,  "Temperature 1",         "°C",  10.0, "int16",  "ro", -200, 1500,  "RTD/TC channel 1 ×10"),
    RegisterDef(100, "Setpoint 0",            "",    1.0,  "uint16", "rw", 0,    65535, "Process setpoint 0"),
    RegisterDef(101, "Setpoint 1",            "",    1.0,  "uint16", "rw", 0,    65535, "Process setpoint 1"),
    RegisterDef(200, "Run Status",            "",    1.0,  "uint16", "ro", 0,    1,     "0=Stopped, 1=Running"),
    RegisterDef(201, "Fault Code",            "",    1.0,  "uint16", "ro", 0,    0,     "0=No fault"),
    RegisterDef(202, "Uptime",                "s",   1.0,  "uint32", "ro", 0,    4294967295,"Uptime in seconds"),
]

SCHNEIDER_MODICON: list[RegisterDef] = [
    RegisterDef(0,   "System Status",         "",    1.0,  "uint16", "ro", 0,    3,     "0=Stop,1=Run,2=Pause,3=Fault"),
    RegisterDef(1,   "Fault Code",            "",    1.0,  "uint16", "ro", 0,    0,     "0=No fault"),
    RegisterDef(2,   "Input Word 1",          "",    1.0,  "uint16", "ro", 0,    65535, "DI word 1"),
    RegisterDef(3,   "Input Word 2",          "",    1.0,  "uint16", "ro", 0,    65535, "DI word 2"),
    RegisterDef(4,   "Output Word 1",         "",    1.0,  "uint16", "rw", 0,    65535, "DO word 1"),
    RegisterDef(5,   "Output Word 2",         "",    1.0,  "uint16", "rw", 0,    65535, "DO word 2"),
    RegisterDef(6,   "Analog In 0",           "mA",  100.0,"uint16", "ro", 400,  2000,  "AI0 ×100 (4-20mA)"),
    RegisterDef(7,   "Analog In 1",           "mA",  100.0,"uint16", "ro", 400,  2000,  "AI1 ×100 (4-20mA)"),
    RegisterDef(8,   "Analog Out 0",          "mA",  100.0,"uint16", "rw", 400,  2000,  "AO0 setpoint ×100"),
    RegisterDef(9,   "Analog Out 1",          "mA",  100.0,"uint16", "rw", 400,  2000,  "AO1 setpoint ×100"),
    RegisterDef(100, "Scan Cycle Time",       "ms",  1.0,  "uint16", "ro", 1,    100,   "PLC scan time"),
    RegisterDef(101, "Free Memory",           "KB",  1.0,  "uint16", "ro", 100,  4096,  "Free application memory"),
]

# ── VFD / Motor Drives ────────────────────────────────────────────────────────

ABB_ACS880: list[RegisterDef] = [
    RegisterDef(1,   "Drive Status Word",     "",    1.0,  "uint16", "ro", 0,    65535, "Status bitmask"),
    RegisterDef(2,   "Output Frequency",      "Hz",  100.0,"int16",  "ro", 0,    10000, "Output freq ×100"),
    RegisterDef(3,   "Motor Speed",           "rpm", 1.0,  "int16",  "ro", 0,    3600,  "Motor speed"),
    RegisterDef(4,   "Motor Current",         "A",   100.0,"uint16", "ro", 0,    50000, "Motor current ×100"),
    RegisterDef(5,   "Motor Torque",          "%",   10.0, "int16",  "ro", -3000,3000,  "Torque ×10"),
    RegisterDef(6,   "DC Link Voltage",       "V",   10.0, "uint16", "ro", 5000, 7000,  "DC bus voltage ×10"),
    RegisterDef(7,   "Drive Temp",            "°C",  10.0, "int16",  "ro", 200,  800,   "Heat sink temp ×10"),
    RegisterDef(8,   "Active Power",          "kW",  100.0,"int16",  "ro", 0,    50000, "Motor power ×100"),
    RegisterDef(9,   "Energy Counter",        "kWh", 10.0, "uint32", "ro", 0,    9999999,"Lifetime energy ×10"),
    RegisterDef(11,  "Fault Word 1",          "",    1.0,  "uint16", "ro", 0,    0,     "Active fault bitmask"),
    RegisterDef(100, "Speed Ref",             "rpm", 1.0,  "uint16", "rw", 0,    3600,  "Speed setpoint"),
    RegisterDef(101, "Torque Ref",            "%",   10.0, "int16",  "rw", -3000,3000,  "Torque setpoint ×10"),
    RegisterDef(102, "Control Word",          "",    1.0,  "uint16", "rw", 0,    65535, "Control command bitmask"),
    RegisterDef(103, "Accel Time",            "s",   10.0, "uint16", "rw", 10,   3000,  "Acceleration ramp ×10"),
    RegisterDef(104, "Decel Time",            "s",   10.0, "uint16", "rw", 10,   3000,  "Deceleration ramp ×10"),
]

# ── SunSpec Models ────────────────────────────────────────────────────────────

SUNSPEC_INVERTER_103: list[RegisterDef] = [
    # Currents
    RegisterDef(0,  "A",       "A",   1.0,  "int16",  "ro", 0,     60000, "AC Total Current"),
    RegisterDef(1,  "AphA",    "A",   1.0,  "int16",  "ro", 0,     20000, "Phase A Current"),
    RegisterDef(2,  "AphB",    "A",   1.0,  "int16",  "ro", 0,     20000, "Phase B Current"),
    RegisterDef(3,  "AphC",    "A",   1.0,  "int16",  "ro", 0,     20000, "Phase C Current"),
    RegisterDef(4,  "A_SF",    "",    1.0,  "int16",  "ro", -3,    0,     "Current Scale Factor"),
    # Phase-to-phase voltages
    RegisterDef(5,  "PPVphAB", "V",   1.0,  "uint16", "ro", 3700,  4200,  "Phase AB Voltage"),
    RegisterDef(6,  "PPVphBC", "V",   1.0,  "uint16", "ro", 3700,  4200,  "Phase BC Voltage"),
    RegisterDef(7,  "PPVphCA", "V",   1.0,  "uint16", "ro", 3700,  4200,  "Phase CA Voltage"),
    # Phase-to-neutral voltages
    RegisterDef(8,  "PhVphA",  "V",   1.0,  "uint16", "ro", 2150,  2450,  "Phase A Voltage"),
    RegisterDef(9,  "PhVphB",  "V",   1.0,  "uint16", "ro", 2150,  2450,  "Phase B Voltage"),
    RegisterDef(10, "PhVphC",  "V",   1.0,  "uint16", "ro", 2150,  2450,  "Phase C Voltage"),
    RegisterDef(11, "V_SF",    "",    1.0,  "int16",  "ro", -2,    0,     "Voltage Scale Factor"),
    # Power
    RegisterDef(12, "W",       "W",   1.0,  "int16",  "ro", 0,     25000, "AC Power"),
    RegisterDef(13, "W_SF",    "",    1.0,  "int16",  "ro", -3,    0,     "Power Scale Factor"),
    # Frequency
    RegisterDef(14, "Hz",      "Hz",  1.0,  "uint16", "ro", 4990,  5010,  "Line Frequency"),
    RegisterDef(15, "Hz_SF",   "",    1.0,  "int16",  "ro", -2,    0,     "Frequency Scale Factor"),
    # Apparent / reactive / power factor
    RegisterDef(16, "VA",      "VA",  1.0,  "int16",  "ro", 0,     27500, "AC Apparent Power"),
    RegisterDef(17, "VA_SF",   "",    1.0,  "int16",  "ro", -3,    0,     "Apparent Power Scale Factor"),
    RegisterDef(18, "VAr",     "var", 1.0,  "int16",  "ro", -5000, 5000,  "AC Reactive Power"),
    RegisterDef(19, "VAr_SF",  "",    1.0,  "int16",  "ro", -3,    0,     "Reactive Power Scale Factor"),
    RegisterDef(20, "PF",      "%",   1.0,  "int16",  "ro", -100,  100,   "Power Factor"),
    RegisterDef(21, "PF_SF",   "",    1.0,  "int16",  "ro", -2,    0,     "Power Factor Scale Factor"),
    # Energy
    RegisterDef(22, "WH",      "Wh",  1.0,  "uint32", "ro", 0,     9999999,"AC Energy"),
    RegisterDef(23, "WH_SF",   "",    1.0,  "int16",  "ro", -3,    0,     "Energy Scale Factor"),
    # DC side
    RegisterDef(24, "DCA",     "A",   1.0,  "int16",  "ro", 0,     40000, "DC Current"),
    RegisterDef(25, "DCA_SF",  "",    1.0,  "int16",  "ro", -3,    0,     "DC Current Scale Factor"),
    RegisterDef(26, "DCV",     "V",   1.0,  "uint16", "ro", 25000, 85000, "DC Voltage"),
    RegisterDef(27, "DCV_SF",  "",    1.0,  "int16",  "ro", -2,    0,     "DC Voltage Scale Factor"),
    RegisterDef(28, "DCW",     "W",   1.0,  "int16",  "ro", 0,     25000, "DC Power"),
    RegisterDef(29, "DCW_SF",  "",    1.0,  "int16",  "ro", -3,    0,     "DC Power Scale Factor"),
    # Temperatures
    RegisterDef(30, "TmpCab",  "°C",  1.0,  "int16",  "ro", 0,     700,   "Cabinet Temperature"),
    RegisterDef(31, "TmpSnk",  "°C",  1.0,  "int16",  "ro", 0,     800,   "Heat Sink Temperature"),
    RegisterDef(32, "TmpTrns", "°C",  1.0,  "int16",  "ro", 0,     700,   "Transformer Temperature"),
    RegisterDef(33, "TmpOt",   "°C",  1.0,  "int16",  "ro", 0,     600,   "Other Temperature"),
    RegisterDef(34, "Tmp_SF",  "",    1.0,  "int16",  "ro", -2,    0,     "Temperature Scale Factor"),
    # State
    RegisterDef(35, "St",      "",    1.0,  "uint16", "ro", 1,     4,     "Operating State"),
    RegisterDef(36, "StVnd",   "",    1.0,  "uint16", "ro", 0,     65535, "Vendor Operating State"),
]

SUNSPEC_METER_201: list[RegisterDef] = [
    # Currents
    RegisterDef(0,  "A",           "A",   1.0,  "int16",  "ro", -60000, 60000, "AC Current"),
    RegisterDef(1,  "AphA",        "A",   1.0,  "int16",  "ro", -20000, 20000, "Phase A Current"),
    RegisterDef(2,  "AphB",        "A",   1.0,  "int16",  "ro", -20000, 20000, "Phase B Current"),
    RegisterDef(3,  "AphC",        "A",   1.0,  "int16",  "ro", -20000, 20000, "Phase C Current"),
    RegisterDef(4,  "A_SF",        "",    1.0,  "int16",  "ro", -3,     0,     "Current Scale Factor"),
    # Phase-to-neutral voltages
    RegisterDef(5,  "PhV",         "V",   1.0,  "int16",  "ro", 2150,   2450,  "Voltage LN"),
    RegisterDef(6,  "PhVphA",      "V",   1.0,  "int16",  "ro", 2150,   2450,  "Phase Voltage AN"),
    RegisterDef(7,  "PhVphB",      "V",   1.0,  "int16",  "ro", 2150,   2450,  "Phase Voltage BN"),
    RegisterDef(8,  "PhVphC",      "V",   1.0,  "int16",  "ro", 2150,   2450,  "Phase Voltage CN"),
    # Phase-to-phase voltages
    RegisterDef(9,  "PPV",         "V",   1.0,  "int16",  "ro", 3700,   4200,  "Voltage LL"),
    RegisterDef(10, "PPVphAB",     "V",   1.0,  "int16",  "ro", 3700,   4200,  "Phase Voltage AB"),
    RegisterDef(11, "PPVphBC",     "V",   1.0,  "int16",  "ro", 3700,   4200,  "Phase Voltage BC"),
    RegisterDef(12, "PPVphCA",     "V",   1.0,  "int16",  "ro", 3700,   4200,  "Phase Voltage CA"),
    RegisterDef(13, "V_SF",        "",    1.0,  "int16",  "ro", -2,     0,     "Voltage Scale Factor"),
    # Frequency
    RegisterDef(14, "Hz",          "Hz",  1.0,  "uint16", "ro", 4990,   5010,  "Frequency"),
    RegisterDef(15, "Hz_SF",       "",    1.0,  "int16",  "ro", -2,     0,     "Frequency Scale Factor"),
    # Real power
    RegisterDef(16, "W",           "W",   1.0,  "int16",  "ro", -50000, 50000, "Total Real Power"),
    RegisterDef(17, "WphA",        "W",   1.0,  "int16",  "ro", -20000, 20000, "Phase A Power"),
    RegisterDef(18, "WphB",        "W",   1.0,  "int16",  "ro", -20000, 20000, "Phase B Power"),
    RegisterDef(19, "WphC",        "W",   1.0,  "int16",  "ro", -20000, 20000, "Phase C Power"),
    RegisterDef(20, "W_SF",        "",    1.0,  "int16",  "ro", -3,     0,     "Real Power Scale Factor"),
    # Apparent power
    RegisterDef(21, "VA",          "VA",  1.0,  "int16",  "ro", 0,      55000, "Apparent Power"),
    RegisterDef(22, "VAphA",       "VA",  1.0,  "int16",  "ro", 0,      20000, "Phase A Apparent"),
    RegisterDef(23, "VAphB",       "VA",  1.0,  "int16",  "ro", 0,      20000, "Phase B Apparent"),
    RegisterDef(24, "VAphC",       "VA",  1.0,  "int16",  "ro", 0,      20000, "Phase C Apparent"),
    RegisterDef(25, "VA_SF",       "",    1.0,  "int16",  "ro", -3,     0,     "Apparent Power Scale Factor"),
    # Reactive power
    RegisterDef(26, "VAR",         "var", 1.0,  "int16",  "ro", -20000, 20000, "Reactive Power"),
    RegisterDef(27, "VARphA",      "var", 1.0,  "int16",  "ro", -10000, 10000, "Phase A Reactive"),
    RegisterDef(28, "VARphB",      "var", 1.0,  "int16",  "ro", -10000, 10000, "Phase B Reactive"),
    RegisterDef(29, "VARphC",      "var", 1.0,  "int16",  "ro", -10000, 10000, "Phase C Reactive"),
    RegisterDef(30, "VAR_SF",      "",    1.0,  "int16",  "ro", -3,     0,     "Reactive Power Scale Factor"),
    # Power factor
    RegisterDef(31, "PF",          "%",   1.0,  "int16",  "ro", -100,   100,   "Power Factor"),
    RegisterDef(32, "PFphA",       "%",   1.0,  "int16",  "ro", -100,   100,   "Phase A Power Factor"),
    RegisterDef(33, "PFphB",       "%",   1.0,  "int16",  "ro", -100,   100,   "Phase B Power Factor"),
    RegisterDef(34, "PFphC",       "%",   1.0,  "int16",  "ro", -100,   100,   "Phase C Power Factor"),
    RegisterDef(35, "PF_SF",       "",    1.0,  "int16",  "ro", -2,     0,     "Power Factor Scale Factor"),
    # Energy export
    RegisterDef(36, "TotWhExp",    "Wh",  1.0,  "uint32", "ro", 0,      9999999, "Total Wh Exported"),
    RegisterDef(37, "TotWhExpPhA", "Wh",  1.0,  "uint32", "ro", 0,      9999999, "Phase A Wh Exported"),
    RegisterDef(38, "TotWhExpPhB", "Wh",  1.0,  "uint32", "ro", 0,      9999999, "Phase B Wh Exported"),
    RegisterDef(39, "TotWhExpPhC", "Wh",  1.0,  "uint32", "ro", 0,      9999999, "Phase C Wh Exported"),
    # Energy import
    RegisterDef(40, "TotWhImp",    "Wh",  1.0,  "uint32", "ro", 0,      9999999, "Total Wh Imported"),
    RegisterDef(41, "TotWhImpPhA", "Wh",  1.0,  "uint32", "ro", 0,      9999999, "Phase A Wh Imported"),
    RegisterDef(42, "TotWhImpPhB", "Wh",  1.0,  "uint32", "ro", 0,      9999999, "Phase B Wh Imported"),
    RegisterDef(43, "TotWhImpPhC", "Wh",  1.0,  "uint32", "ro", 0,      9999999, "Phase C Wh Imported"),
    RegisterDef(44, "TotWh_SF",    "",    1.0,  "int16",  "ro", -3,     0,       "Energy Scale Factor"),
]

# ── Keyword-to-map registry ───────────────────────────────────────────────────

DEVICE_TYPES: dict[str, list[RegisterDef]] = {
    # Inverter brands / models
    "sma":           SMA_SUNNY_BOY,
    "sunny boy":     SMA_SUNNY_BOY,
    "sunny tripower":SMA_SUNNY_BOY,
    "fronius":       FRONIUS_SYMO,
    "symo":          FRONIUS_SYMO,
    "primo":         FRONIUS_SYMO,
    "abb react":     ABB_REACT2,
    "react2":        ABB_REACT2,
    "solaredge":     SOLAREDGE_SE,
    "growatt":       GROWATT_SPH,
    "sph":           GROWATT_SPH,
    # Generic inverter fallback
    "inverter":      SMA_SUNNY_BOY,
    "pv":            SMA_SUNNY_BOY,
    # Energy meters
    "meter":         GENERIC_ENERGY_METER,
    "carlo":         CARLO_GAVAZZI_EM,
    "gavazzi":       CARLO_GAVAZZI_EM,
    "em24":          CARLO_GAVAZZI_EM,
    "em340":         CARLO_GAVAZZI_EM,
    # Battery storage
    "byd":           BYD_HVM,
    "hvm":           BYD_HVM,
    "battery":       BYD_HVM,
    "bess":          BYD_HVM,
    "ess":           BYD_HVM,
    # PLC / RTU
    "plc":           GENERIC_PLC,
    "rtu":           GENERIC_PLC,
    "schneider":     SCHNEIDER_MODICON,
    "modicon":       SCHNEIDER_MODICON,
    "m340":          SCHNEIDER_MODICON,
    "m580":          SCHNEIDER_MODICON,
    # VFD / drives
    "vfd":           ABB_ACS880,
    "acs880":        ABB_ACS880,
    "drive":         ABB_ACS880,
    # SunSpec models (exact key lookup by DID)
    "SUNSPEC_INVERTER_103": SUNSPEC_INVERTER_103,
    "SUNSPEC_METER_201":    SUNSPEC_METER_201,
    # SunSpec keyword shortcuts
    "sunspec inverter": SUNSPEC_INVERTER_103,
    "sunspec meter":    SUNSPEC_METER_201,
}

# Default fallback when no keyword matches
DEFAULT_MAP: list[RegisterDef] = GENERIC_PLC


def lookup(device_type: str, device_name: str = "") -> tuple[str, list[RegisterDef]]:
    """
    Return (matched_key, register_list) for the best matching device map.
    Searches device_type first, then device_name. Falls back to DEFAULT_MAP.
    """
    search_text = f"{device_type} {device_name}".lower()
    for keyword, reg_map in DEVICE_TYPES.items():
        if keyword in search_text:
            return keyword, reg_map
    return "generic", DEFAULT_MAP


def registers_summary(regs: list[RegisterDef]) -> list[dict]:
    """Return a JSON-serialisable summary of a register map."""
    return [
        {
            "address":     r.address,
            "name":        r.name,
            "unit":        r.unit,
            "scale":       r.scale,
            "type":        r.data_type,
            "access":      r.access,
            "min":         r.min_val,
            "max":         r.max_val,
            "description": r.description,
        }
        for r in regs
    ]
