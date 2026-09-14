import sys
import struct
import threading
import time
from datetime import datetime

from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusSlaveContext,
    ModbusServerContext,
)

from pymodbus.server.sync import StartTcpServer

import json

# ============================================================
# DATABLOCK
# ============================================================

class LoggingDataBlock(ModbusSequentialDataBlock):

    def __init__(
        self,
        block_name,
        address,
        values
    ):

        self.block_name = block_name

        super().__init__(
            address,
            values
        )

    def getValues(
        self,
        address,
        count=1
    ):

        global read_count
        global last_read

        values = super().getValues(
            address,
            count
        )

        read_count += 1
        last_read = datetime.now()

        if log_reads:

            print(
                f"[{last_read:%H:%M:%S}] "
                f"READ "
                f"{self.block_name}{address} "
                f"COUNT={count}"
            )

        return values

    def setValues(
        self,
        address,
        values
    ):

        if log_writes:

            print(
                f"[{datetime.now():%H:%M:%S}] "
                f"WRITE "
                f"{self.block_name}{address} "
                f"VALUES={values}"
            )

        return super().setValues(
            address,
            values
        )

# ============================================================
# CONFIG
# ============================================================

DEFAULT_UNIT_ID = 1
DEFAULT_PORT = 502
units = {}
context = None
store = None

def get_config():

    if len(sys.argv) >= 2:

        unit_id = int(sys.argv[1])

        port = (
            int(sys.argv[2])
            if len(sys.argv) >= 3
            else DEFAULT_PORT
        )

        return unit_id, port

    unit_id_input = input(
        "Unit IDs "
    ).strip() or DEFAULT_UNIT_ID

    unit_ids = [
        int(x.strip())
        for x in unit_id_input.split(",")
    ]

    port = int(
        input(f"Port [{DEFAULT_PORT}]: ")
        or DEFAULT_PORT
    )

    return unit_ids, port

def build_units(unit_ids):

    global UNIT_IDS
    global units
    global current_unit
    global context
    global store

    UNIT_IDS = unit_ids

    units.clear()

    for unit_id in UNIT_IDS:

        units[unit_id] = ModbusSlaveContext(
            co=LoggingDataBlock(
                "CO",
                0,
                [0] * 65535
            ),

            di=LoggingDataBlock(
                "DI",
                0,
                [0] * 65535
            ),

            hr=LoggingDataBlock(
                "HR",
                0,
                [0] * 65535
            ),

            ir=LoggingDataBlock(
                "IR",
                0,
                [0] * 65535
            ),

            zero_mode=True
        )

    current_unit = UNIT_IDS[0]
    store = units[current_unit]

    if context is None:

        context = ModbusServerContext(
            slaves=units,
            single=False
        )

UNIT_IDS, PORT = get_config()
build_units(UNIT_IDS)
current_unit = UNIT_IDS[0]

def save_config(filename):

    data = {}

    data["port"] = PORT
    data["unit_ids"] = UNIT_IDS

    data["units"] = {}

    modbus_types = {
        "co": 1,
        "di": 2,
        "hr": 3,
        "ir": 4
    }

    for unit_id in UNIT_IDS:

        unit_data = {}

        for name, modbus_type in modbus_types.items():

            registers = {}

            for addr in range(65535):

                value = units[unit_id].getValues(
                    modbus_type,
                    addr,
                    count=1
                )[0]

                if value != 0:

                    registers[str(addr)] = value

            unit_data[name] = registers

        data["units"][str(unit_id)] = unit_data

    data["counters"] = counters
    data["clocks"] = clocks
    data["routines"] = routines

    with open(filename, "w") as f:

        json.dump(
            data,
            f,
            indent=4
        )

    print(
        f"Configuration saved to {filename}"
    )
    
def load_config(filename):

    global current_unit
    global counters
    global clocks
    global routines

    with open(filename, "r") as f:

        data = json.load(f)

    #
    # Restore Unit IDs
    #

    if "unit_ids" in data:

        build_units(
            data["unit_ids"]
        )

        print(
            "Unit IDs restored: "
            + ", ".join(
                map(str, UNIT_IDS)
            )
        )

    #
    # Stop existing counters
    #

    for key in list(counters.keys()):

        counters[key]["running"] = False

    counters = {}

    #
    # Stop existing clocks
    #

    for key in list(clocks.keys()):

        if isinstance(clocks[key], dict):

            clocks[key]["running"] = False

    clocks = {}

    #
    # Clear all Modbus data
    #

    for unit_id in UNIT_IDS:

        for data_type in [1, 2, 3, 4]:

            units[unit_id].setValues(
                data_type,
                0,
                [0] * 65535
            )

    #
    # Restore registers
    #

    if "units" in data:

        print(
            "Save file contains Unit IDs: "
            + ", ".join(
                map(str, data["unit_ids"])
            )
        )

        for unit_id, unit_data in data["units"].items():

            unit_id = int(unit_id)

            if unit_id not in units:

                continue

            #
            # New format
            #

            if (
                "co" in unit_data
                or "di" in unit_data
                or "hr" in unit_data
                or "ir" in unit_data
            ):

                for addr, value in unit_data.get(
                    "co",
                    {}
                ).items():

                    units[unit_id].setValues(
                        1,
                        int(addr),
                        [value]
                    )

                for addr, value in unit_data.get(
                    "di",
                    {}
                ).items():

                    units[unit_id].setValues(
                        2,
                        int(addr),
                        [value]
                    )

                for addr, value in unit_data.get(
                    "hr",
                    {}
                ).items():

                    units[unit_id].setValues(
                        3,
                        int(addr),
                        [value]
                    )

                for addr, value in unit_data.get(
                    "ir",
                    {}
                ).items():

                    units[unit_id].setValues(
                        4,
                        int(addr),
                        [value]
                    )

            #
            # Intermediate format
            #

            elif "registers" in unit_data:

                for addr, value in unit_data[
                    "registers"
                ].items():

                    units[unit_id].setValues(
                        3,
                        int(addr),
                        [value]
                    )

    #
    # Legacy format
    #

    elif "registers" in data:

        print(
            "Legacy single-unit save detected"
        )

        for addr, value in data[
            "registers"
        ].items():

            units[current_unit].setValues(
                3,
                int(addr),
                [value]
            )

    #
    # Restore counters
    #

    if "counters" in data:

        for key, cfg in data[
            "counters"
        ].items():

            #
            # New format
            #

            if (
                isinstance(cfg, dict)
                and "unit" in cfg
                and "addr" in cfg
            ):

                counters[key] = cfg

                threading.Thread(
                    target=counter_worker,
                    args=(key,),
                    daemon=True
                ).start()

            #
            # Old format
            #

            elif isinstance(cfg, dict):

                start_counter(
                    "hr",
                    int(key),
                    cfg["min"],
                    cfg["max"],
                    cfg["period"]
                )

        print(
            f"Loaded {len(data['counters'])} counters"
        )

    #
    # Restore clocks
    #

    if "clocks" in data:

        for key, cfg in data[
            "clocks"
        ].items():

            #
            # New format
            #

            if (
                isinstance(cfg, dict)
                and "unit" in cfg
                and "addr" in cfg
            ):

                clocks[key] = cfg

                threading.Thread(
                    target=clock_worker,
                    args=(key,),
                    daemon=True
                ).start()

            #
            # Old format
            #

            elif cfg:

                start_clock(
                    "hr",
                    int(key)
                )

        print(
            f"Loaded {len(data['clocks'])} clocks"
        )

    #
    # Restore routines
    #

    if "routines" in data:

        routines = data["routines"]

        print(
            f"Loaded {len(routines)} routines"
        )

    print(
        f"Configuration restored from {filename}"
    )
    
# ============================================================
# GLOBALS
# ============================================================

read_count = 0
last_read = None

running = True

log_reads = False
log_writes = False

counters = {}
clocks = {}
routines = {}
routine_running = {}

# ============================================================
# SERVER
# ============================================================

def print_banner():

    print("")
    print("======================================")
    print(" Modbus TCP Simulator")
    print("======================================")
    print(f"Unit IDs : ")
    print(f"{', '.join(map(str, UNIT_IDS))}")
    print(f"Port          : {PORT}")
    print(f"Read Logging  : {log_reads}")
    print(f"Write Logging : {log_writes}")
    print("======================================")
    print("")

def server_thread():

    StartTcpServer(
        context,
        address=("0.0.0.0", PORT)
    )

# ============================================================
# UNIT IDs
# ============================================================

def select_unit(unit_id):

    global current_unit

    if unit_id not in units:

        print("Unit ID not found")
        return

    current_unit = unit_id

    print(
        f"Current Unit ID = {unit_id}"
    )
    
def show_units():

    print("")
    print("Configured Unit IDs")
    print("-------------------")

    for unit_id in UNIT_IDS:

        marker = " < CURRENT" if unit_id == current_unit else ""

        print(
            f"{unit_id}{marker}"
        )

    print("")

# ============================================================
# BOOL
# ============================================================

BOOL_TYPES = {
    "co": 1,
    "di": 2
}

def set_bool(obj_type, addr, value):

    obj_type = obj_type.lower()

    if obj_type not in BOOL_TYPES:

        print(
            "Type must be 'co' or 'di'"
        )

        return

    units[current_unit].setValues(
        BOOL_TYPES[obj_type],
        addr,
        [int(value)]
    )

    print(
        f"{obj_type.upper()}{addr} = {value}"
    )
    
def show_bool(obj_type, addr):

    obj_type = obj_type.lower()

    if obj_type not in BOOL_TYPES:

        print(
            "Type must be 'co' or 'di'"
        )

        return

    value = units[current_unit].getValues(
        BOOL_TYPES[obj_type],
        addr,
        count=1
    )[0]

    print(
        f"{obj_type.upper()}{addr} = {value}"
    )

# ============================================================
# REGISTERS
# ============================================================

REG_TYPES = {
    "hr": 3,
    "ir": 4
}

def show_word(
    reg_type,
    addr
):

    reg_type = reg_type.lower()

    if reg_type not in REG_TYPES:

        print(
            "Type must be 'hr' or 'ir'"
        )

        return

    value = units[current_unit].getValues(
        REG_TYPES[reg_type],
        addr,
        count=1
    )[0]

    print(
        f"{reg_type.upper()}{addr} = {value}"
    )

def show_range(start, end):

    values = units[current_unit].getValues(
        3,
        start,
        count=(end - start + 1)
    )

    for i, value in enumerate(values):
        print(
            f"HR{start + i} = {value}"
        )

def set_word(
    reg_type,
    addr,
    value
):

    reg_type = reg_type.lower()

    if reg_type not in REG_TYPES:

        print(
            "Type must be 'hr' or 'ir'"
        )

        return

    units[current_unit].setValues(
        REG_TYPES[reg_type],
        addr,
        [value]
    )

    print(
        f"{reg_type.upper()}{addr} = {value}"
    )

def clear_registers():

    for addr in range(65535):

        store.setValues(
            3,
            addr,
            [0]
        )

    print("All registers cleared")
    
# ============================================================
# FLOATS
# ============================================================

def set_float(
    reg_type,
    addr,
    value
    ):

    reg_type = reg_type.lower()

    if reg_type not in REG_TYPES:

        print(
            "Type must be 'hr' or 'ir'"
        )

        return

    words = struct.unpack(
        ">HH",
        struct.pack(">f", float(value))
    )

    units[current_unit].setValues(
        REG_TYPES[reg_type],
        addr,
        list(words)
    )

    print(
        f"{reg_type.upper()}{addr}-{addr+1} = {value}"
    )

def show_float(
    reg_type,
    addr
    ):

    reg_type = reg_type.lower()

    if reg_type not in REG_TYPES:

        print(
            "Type must be 'hr' or 'ir'"
        )

        return

    words = units[current_unit].getValues(
        REG_TYPES[reg_type],
        addr,
        count=2
    )

    value = struct.unpack(
        ">f",
        struct.pack(">HH", *words)
    )[0]

    print(
        f"{reg_type.upper()}{addr}-{addr+1} = {value}"
    )

# ============================================================
# DOUBLE INTEGER
# ============================================================

def set_dint(
    reg_type,
    addr,
    value
    ):

    reg_type = reg_type.lower()

    if reg_type not in REG_TYPES:

        print(
            "Type must be 'hr' or 'ir'"
        )

        return

    hi = (value >> 16) & 0xFFFF
    lo = value & 0xFFFF

    units[current_unit].setValues(
        REG_TYPES[reg_type],
        addr,
        [hi, lo]
    )

    print(
        f"{reg_type.upper()}"
        f"{addr}-{addr+1} = {value}"
    )

def show_dint(
    reg_type,
    addr
    ):

    reg_type = reg_type.lower()

    if reg_type not in REG_TYPES:

        print(
            "Type must be 'hr' or 'ir'"
        )

        return

    words = units[current_unit].getValues(
        REG_TYPES[reg_type],
        addr,
        count=2
    )

    value = (
        (words[0] << 16)
        | words[1]
    )

    print(
        f"{reg_type.upper()}"
        f"{addr}-{addr+1} = {value}"
    )
    
# ============================================================
# COUNTERS
# ============================================================

def write_register_silent(addr, values):

    units[current_unit].store["h"].setValues(
        addr,
        values
    )

def counter_worker(key):

    cfg = counters[key]

    unit_id = cfg["unit"]
    addr = cfg["addr"]

    value = cfg["min"]

    while (
        key in counters
        and counters[key]["running"]
    ):

        units[unit_id].setValues(
            cfg["type"],
            addr,
            [value]
        )


        value += 1

        if value > cfg["max"]:
            value = cfg["min"]

        time.sleep(cfg["period"])

def start_counter(
    reg_type,
    addr,
    minimum,
    maximum,
    period
    ):

    key = f"{current_unit}:{reg_type}:{addr}"

    counters[key] = {
        "running": True,
        "unit": current_unit,
        "type": REG_TYPES[reg_type],
        "addr": addr,
        "min": minimum,
        "max": maximum,
        "period": period
    }

    threading.Thread(
        target=counter_worker,
        args=(key,),
        daemon=True
    ).start()

def stop_counter(addr):

    key = f"{current_unit}:{reg_type}:{addr}"

    if key in counters:

        counters[key]["running"] = False

        print(
            f"Counter stopped on "
            f"Unit {current_unit} HR{addr}"
        )

def stop_all_counters():

    for cfg in counters.values():

        cfg["running"] = False

    time.sleep(0.1)

    counters.clear()

    print("All counters stopped")

# ============================================================
# WRITE HEX IN DECIMAL
# ============================================================
    
def set_hex(
    reg_type,
    addr,
    value
    ):

    reg_type = reg_type.lower()

    if reg_type not in REG_TYPES:

        print(
            "Type must be 'hr' or 'ir'"
        )

        return

    value = int(value, 16)

    units[current_unit].setValues(
        REG_TYPES[reg_type],
        addr,
        [value]
    )

    print(
        f"{reg_type.upper()}{addr} = "
        f"16#{value:X} ({value})"
    )
    
def show_hex(
    reg_type,
    addr
    ):

    reg_type = reg_type.lower()

    if reg_type not in REG_TYPES:

        print(
            "Type must be 'hr' or 'ir'"
        )

        return

    value = units[current_unit].getValues(
        REG_TYPES[reg_type],
        addr,
        count=1
    )[0]

    print(
        f"{reg_type.upper()}{addr} = "
        f"16#{value:X} ({value})"
    )

def set_dhex(
    reg_type,
    addr,
    value
    ):

    reg_type = reg_type.lower()

    if reg_type not in REG_TYPES:

        print(
            "Type must be 'hr' or 'ir'"
        )

        return

    value = int(value, 16)

    hi = (value >> 16) & 0xFFFF
    lo = value & 0xFFFF

    units[current_unit].setValues(
        REG_TYPES[reg_type],
        addr,
        [hi, lo]
    )

    print(
        f"{reg_type.upper()}"
        f"{addr}-{addr+1} = "
        f"16#{value:X} ({value})"
    )
    
def show_dhex(
    reg_type,
    addr
    ):

    reg_type = reg_type.lower()

    if reg_type not in REG_TYPES:

        print(
            "Type must be 'hr' or 'ir'"
        )

        return

    words = units[current_unit].getValues(
        REG_TYPES[reg_type],
        addr,
        count=2
    )

    value = (
        (words[0] << 16)
        | words[1]
    )

    print(
        f"{reg_type.upper()}"
        f"{addr}-{addr+1} = "
        f"16#{value:X} ({value})"
    )

# ============================================================
# CLOCK
# ============================================================

from datetime import timedelta

def clock_worker(key):

    while (
        key in clocks
        and clocks[key]["running"]
    ):

        cfg = clocks[key]

        unit_id = cfg["unit"]
        addr = cfg["addr"]

        now = datetime.now() + timedelta(
            hours=cfg["tz_shift"]
        )

        reg1 = now.microsecond // 1000

        reg2 = (
            (now.minute << 8)
            | now.hour
        )

        reg3 = (
            (now.day << 8)
            | now.month
        )

        reg4 = now.year

        units[unit_id].setValues(
            cfg["type"],
            addr,
            [
                reg1,
                reg2,
                reg3,
                reg4
            ]
        )

        time.sleep(1)

def start_clock(
    reg_type,
    addr,
    tz_shift=0
    ):

    key = f"{current_unit}:{reg_type}:{addr}"

    clocks[key] = {
        "running": True,
        "unit": current_unit,
        "type": REG_TYPES[reg_type],
        "addr": addr,
        "tz_shift": tz_shift
    }

    threading.Thread(
        target=clock_worker,
        args=(key,),
        daemon=True
    ).start()

    print(
        f"Clock started on "
        f"{reg_type.upper()}"
        f"{addr}-{addr+3} "
        f"(UTC{tz_shift:+d})"
    )
    
def stop_clock(
    reg_type,
    addr
    ):

    key = f"{current_unit}:{reg_type}:{addr}"

    if key in clocks:

        clocks[key]["running"] = False

        print(
            f"Clock stopped on "
            f"{reg_type.upper()}{addr}"
        )

# ============================================================
# ROUTINE
# ============================================================

def create_routine(name):

    routines[name] = []

    print(
        f"Routine '{name}' created"
    )
    
def add_routine(name, step):

    if name not in routines:

        print("Routine not found")
        return

    routines[name].append(step)

    print(
        f"Added to {name}"
    )

def routine_worker(name):

    routine_running[name] = True

    for step in routines[name]:
    
        if not routine_running.get(name, False):
            
            break

        if step[0] == "timer":

            time.sleep(float(step[1]))

        elif step[0] == "set":

            set_word(
                int(step[1]),
                int(step[2])
            )

        elif step[0] == "seth":

            set_hex(
                int(step[1]),
                step[2]
            )

        elif step[0] == "setf":

            set_float(
                int(step[1]),
                float(step[2])
            )

        elif step[0] == "setd":

            set_dint(
                int(step[1]),
                int(step[2])
            )

    routine_running[name] = False

def start_routine(name):

    if name not in routines:

        print("Routine not found")
        return

    if routine_running.get(name, False):

        print("Routine already running")
        return

    threading.Thread(
        target=routine_worker,
        args=(name,),
        daemon=True
    ).start()

    print(f"Routine '{name}' started")

def stop_routine(name):

    if name not in routine_running:

        print("Routine not running")
        return

    routine_running[name] = False

    print(f"Routine '{name}' stopped")

# ============================================================
# STATUS
# ============================================================

def show_status():

    print("")
    print("STATUS")
    print("------")
    print(f"Reads       : {read_count}")
    print(f"Log Reads   : {log_reads}")
    print(f"Log Writes  : {log_writes}")

    if last_read:

        print(
            f"Last Read  : "
            f"{last_read:%Y-%m-%d %H:%M:%S}"
        )

    else:

        print("Last Read  : Never")

    print("")

def show_info():

    print("")
    print("INFO")
    print("----")
    print(f"Unit ID      : {UNIT_IDS}")
    print(f"Port         : {PORT}")
    print(f"Read Logging : {log_reads}")
    print(f"Write Logging: {log_writes}")
    print(f"Counters     : {len(counters)}")
    print(f"Clocks       : {len(clocks)}")
    print("")

# ============================================================
# CLI
# ============================================================

def cli():

    global running
    global log_reads
    global log_writes

    print("")
    print("Commands")
    print("--------")
    print("")
    print("setb <co|di> <addr> <0|1>")
    print("showb <co|di> <addr>")
    print("")
    print("setw <hr|ir> <addr> <value>")
    print("setf <hr|ir> <addr> <float>")
    print("setd <hr|ir> <addr> <value>")
    print("seth <hr|ir> <addr> <value>")
    print("")
    print("showw <hr|ir> <addr>")
    print("showf <hr|ir> <addr>")
    print("showd <hr|ir> <addr>")
    print("showh <hr|ir> <addr>")
    print("clear")
    print("")
    print("counter <hr|ir> <addr> <min> <max> <sec>")
    print("stopc <hr|ir> <addr>")
    print("stopallc")
    print("")
    print("startclk <hr|ir> <addr> <tz>")
    print("stopclk <hr|ir> <addr>")
    print("")
    print("creatertn <name>")
    print("addrtn <name> timer 5")
    print("addrtn <name> <set_command>")
    print("startrtn <name>")
    print("stoprtn <name>")
    print("listrtn")
    print("showrtn <name>")
    print("")
    print("log on")
    print("log off")
    print("")
    print("wlog on")
    print("wlog off")
    print("")
    print("unit <id>")
    print("units")
    print("")
    print("save <filename>")
    print("load <filename>")
    print("")
    print("status")
    print("info")
    print("quit")
    print("")

    while running:

        try:

            command = input(
                f"[{current_unit}]> "
            ).strip()

            if not command:

                continue

            parts = command.split()

            if parts[0] == "setb":

                set_bool(
                    parts[1],
                    int(parts[2]),
                    int(parts[3])
                )

            elif parts[0] == "showb":

                show_bool(
                    parts[1],
                    int(parts[2])
                )
                
            elif parts[0] == "setw":

                set_word(
                    parts[1],
                    int(parts[2]),
                    int(parts[3])
                )

            elif parts[0] == "showw":

                show_word(
                    parts[1],
                    int(parts[2])
                )

            elif parts[0] == "setf":

                set_float(
                    parts[1],
                    int(parts[2]),
                    float(parts[3])
                )

            elif parts[0] == "showf":

                show_float(
                    parts[1],
                    int(parts[2])
                )

            elif parts[0] == "setd":

                set_dint(
                    parts[1],
                    int(parts[2]),
                    int(parts[3])
                )
            
            elif parts[0] == "showd":

                show_dint(
                    parts[1],
                    int(parts[2])
                )

            elif parts[0] == "seth":

                set_hex(
                    parts[1],
                    int(parts[2]),
                    parts[3]
                )

            elif parts[0] == "showh":

                show_hex(
                    parts[1],
                    int(parts[2])
                )

            elif parts[0] == "setdh":

                set_dhex(
                    parts[1],
                    int(parts[2]),
                    parts[3]
                )

            elif parts[0] == "showdh":

                show_dhex(
                    parts[1],
                    int(parts[2])
                )
                
            elif parts[0] == "unit":

                select_unit(
                    int(parts[1])
                )
                
            elif parts[0] == "units":

                show_units()
                
            elif parts[0] == "save":

                save_config(parts[1])

            elif parts[0] == "load":

                load_config(parts[1])
                
            elif parts[0] == "clear":

                clear_registers()

            elif parts[0] == "counter":

                start_counter(
                    parts[1],
                    int(parts[2]),
                    int(parts[3]),
                    int(parts[4]),
                    float(parts[5])
                )

            elif parts[0] == "stopc":

                stop_counter(
                    int(parts[1])
                )
                
            elif parts[0] == "stopallc":

                stop_all_counters()

            elif parts[0] == "startclk":

                tz_shift = (
                    int(parts[3])
                    if len(parts) >= 4
                    else 0
                )

                start_clock(
                    parts[1],
                    int(parts[2]),
                    tz_shift
                )

            elif parts[0] == "stopclk":

                stop_clock(
                    parts[1],
                    int(parts[2])
                )

            elif parts[0] == "creatertn":

                create_routine(
                    parts[1]
                )

            elif parts[0] == "addrtn":

                name = parts[1]

                add_routine(
                    name,
                    parts[2:]
                )

            elif parts[0] == "startrtn":

                start_routine(
                    parts[1]
                )

            elif parts[0] == "stoprtn":

                stop_routine(
                    parts[1]
                )

            elif parts[0] in ("listrtn"):

                if not routines:

                    print("No routines defined")

                else:

                    print("Routines")

                    for name in routines:

                        print(
                            f" - {name}"
                        )

            elif parts[0] in ("showrtn"):

                name = parts[1]

                if name not in routines:

                    print("Routine not found")

                else:

                    print("")
                    print(f"Routine: {name}")
                    print("")

                    for i, step in enumerate(
                        routines[name],
                        start=1
                    ):

                        print(
                            f"{i}: {' '.join(map(str, step))}"
                        )

                    print("")

            elif parts[0] == "log":

                if len(parts) != 2:

                    print("Usage: log on|off")

                elif parts[1].lower() == "on":

                    log_reads = True
                    print("Read logging ON")

                elif parts[1].lower() == "off":

                    log_reads = False
                    print("Read logging OFF")

                else:

                    print("Usage: log on|off")
                    
            elif parts[0] == "wlog":

                if len(parts) != 2:

                    print("Usage: wlog on|off")

                elif parts[1].lower() == "on":

                    log_writes = True
                    print("Write logging ON")

                elif parts[1].lower() == "off":

                    log_writes = False
                    print("Write logging OFF")

                else:

                    print("Usage: wlog on|off")

            elif parts[0] == "status":

                show_status()

            elif parts[0] == "info":

                show_info()

            elif parts[0] == "quit":

                running = False

                for addr in list(counters.keys()):
                    stop_counter(addr)

                break

            else:

                print("Unknown command")

        except Exception as ex:

            print(f"ERROR: {ex}")


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    print_banner()

    threading.Thread(
        target=server_thread,
        daemon=True
    ).start()

    cli()