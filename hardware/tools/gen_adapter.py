#!/usr/bin/env python3
"""
AGX adapter board (variant A): Xavier camera connector -> 4 x 40-pin FPC.

Outputs (hardware/adapter/):
  xavier_connector_map.csv   QTH-060 pin -> Xavier signal -> adapter net -> destination
  fpc_k_pinout.csv           per stereo board: FPC pin -> adapter net
  adapter_netlist.csv        functional netlist (ICs by pin function)
  adapter_bom.csv
and hardware/kicad/adapter_board/adapter_board.kicad_pcb (+ preview):
  4 FPC footprints with their nets, keep-outs for the Samtec connector and
  the support circuits (import the QTH footprint from Samtec or Antmicro).
"""
import csv
import os

import fpc_pinout
from kicadgen import Board, fpc_footprint
from xavier_cam_connector import PINMAP, fpc_to_xavier

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, "..", "adapter"))
KOUT = os.path.normpath(os.path.join(HERE, "..", "kicad", "adapter_board"))
PAIRS = ["front", "rear", "left", "right"]


def fpc_nets(k):
    """adapter-side net per FPC pin for stereo board k"""
    m = fpc_to_xavier(k)
    out = []
    for pin, n, _ in fpc_pinout.FPC40:
        if n == "GND":
            out.append("GND")
        elif n in m:
            out.append(m[n])
        elif n == "VIN_5V":
            out.append(f"S{k}_VIN_5V")
        elif n == "RSVD":
            out.append(f"S{k}_RSVD{pin}")
        else:
            out.append(f"S{k}_{n}")
    return out


SUPPORT = [
    # ref, part, value/notes, [(function, net)]
    ("U1", "TCA9546A (TSSOP-16)", "I2C mux @0x70, VCC = 1V8_CONN",
     [("SCL/SDA", "I2C_GP3_CLK / I2C_GP3_DAT"), ("A0..A2", "GND"), ("RESET#", "1V8_CONN via 10k"),
      ("SC0/SD0", "S0_I2C_SCL / S0_I2C_SDA"), ("SC1/SD1", "S1_I2C_SCL / S1_I2C_SDA"),
      ("SC2/SD2", "S2_I2C_SCL / S2_I2C_SDA"), ("SC3/SD3", "S3_I2C_SCL / S3_I2C_SDA")]),
    ("RN1..RN4", "2.2k pull-ups", "per mux channel to 1V8_CONN", [("x", "Sk_I2C_SCL/SDA")]),
    ("U2", "TCA6416A (TSSOP-24)", "GPIO expander @0x20, VCCI = VCCP = 1V8_CONN",
     [("SCL/SDA", "I2C_GP3_CLK / I2C_GP3_DAT"), ("ADDR", "GND"), ("RESET#", "CAM1_RST (conn pin 92) + 10k pull-up"),
      ("P00..P03 (out)", "S0..S3_PWR_EN"), ("P04..P07 (out)", "S0..S3_VIN_EN"),
      ("P10..P13 (in)", "S0..S3_STATUS"), ("P14..P17 (out, OD use)", "S0..S3_FPGA_PROGRAMN")]),
    ("U3", "RP2040 + W25Q16JV + 12 MHz XTAL", "sync controller (firmware/sync_controller)",
     [("GP2..GP5", "TRIG0..TRIG3 (3V3)"), ("GP6", "SYNC_OUT (3V3)"),
      ("GP8..GP15", "TOUT0_L/R of S0..S3 (3V3, optional verification)"), ("USB", "J6 USB-C -> Xavier USB")]),
    ("U4, U5", "SN74AXC4T774 (4-bit dual-supply, dir per bit)", "3V3 <-> 1V8",
     [("A (3V3)", "TRIG0..3"), ("B (1V8)", "S0..S3_TRIG")]),
    ("U6", "SN74AXC1T45", "SYNC_OUT 3V3 -> 1V8", [("A", "SYNC_OUT"), ("B", "GPIO10 (conn pin 85)")]),
    ("U7, U8", "SN74AXC4T774", "TOUT0 1V8 -> 3V3 (optional)", [("B", "Sk_TOUT0_L/R"), ("A", "RP2040 GP8..15")]),
    ("U9", "5 V / 4 A buck (e.g. TPS56637)", "12 V in -> +5V_CAM", [("VIN", "+12V_IN"), ("VOUT", "+5V_CAM")]),
    ("U10..U13", "current-limited 5 V switch, 1.8 V-compatible EN (e.g. TPS2553 family - VERIFY VIH)",
     "ILIM ~0.8 A per stereo board", [("IN", "+5V_CAM"), ("OUT", "Sk_VIN_5V"), ("EN", "Sk_VIN_EN")]),
    ("J1", "Samtec QTH-060-03-L-D-A", "to AGX devkit camera connector (bottom side)", [("see", "xavier_connector_map.csv")]),
    ("J2..J5", "Hirose FH12-40S-0.5SH(55)", "FPC to stereo board 0..3", [("see", "fpc_k_pinout.csv")]),
    ("J7", "DC barrel / 2-pin terminal", "+12V_IN, >= 2 A, TVS + reverse-polarity FET", [("1", "+12V_IN"), ("2", "GND")]),
]


def main():
    os.makedirs(OUT, exist_ok=True)
    # where each Xavier pin goes on the adapter
    dest = {}
    for k in range(4):
        for pin, net in enumerate(fpc_nets(k), 1):
            if net.startswith("CSI"):
                dest[net] = f"J{k + 2} (stereo board {k}, {PAIRS[k]}) pin {pin}"
    dest.update({"I2C_GP3_CLK": "U1 TCA9546A + U2 TCA6416A SCL", "I2C_GP3_DAT": "U1 TCA9546A + U2 TCA6416A SDA",
                 "GPIO10": "U6 B (SYNC_OUT, 1.8 V)", "CAM1_RST": "U2 TCA6416A RESET#",
                 "1V8_CONN": "1.8 V logic (mux, expander, shifters B side, pull-ups)",
                 "3V3_CONN": "3.3 V logic (RP2040, shifters A side) - camera power comes from J7",
                 "AVDD_CAM_2V8": "not used", "GND": "GND"})
    with open(os.path.join(OUT, "xavier_connector_map.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["qth_pin", "xavier_signal", "adapter_destination"])
        for p in list(range(1, 121)) + ["MP"]:
            s = PINMAP[p]
            w.writerow([p, s or "NC", dest.get(s, "leave open (unused)") if s else "leave open"])
    with open(os.path.join(OUT, "fpc_k_pinout.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["fpc_pin", "stereo_board_net", "description"] + [f"adapter_J{k + 2}_net (board {k}, {PAIRS[k]})" for k in range(4)])
        nets = [fpc_nets(k) for k in range(4)]
        for i, (pin, n, d) in enumerate(fpc_pinout.FPC40):
            w.writerow([pin, n, d] + [nets[k][i] for k in range(4)])
    with open(os.path.join(OUT, "adapter_netlist.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["ref", "part", "value / note", "pin / function", "net"])
        for ref, part, val, conns in SUPPORT:
            for fn, net in conns:
                w.writerow([ref, part, val, fn, net])
    with open(os.path.join(OUT, "adapter_bom.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["ref", "part", "value / note"])
        for ref, part, val, _ in SUPPORT:
            w.writerow([ref, part, val])

    # ---------------- KiCad demo: 4 FPC sockets with nets + keep-outs
    b = Board("adapter_board", 120.0, 56.0)
    for x in (-57, 57):
        for y in (-25, 25):
            b.hole(x, y)
    xs = [-42.0, -14.0, 14.0, 42.0]
    for k in range(4):
        fpc_footprint(b, f"J{k + 2}", xs[k], -22.5, fpc_nets(k), side="top")
        b.text(f"STEREO {k} ({PAIRS[k]})", xs[k], -16.0, "F.SilkS", 1.0)
    b.block(0.0, 8.0, 46.0, 9.0, "J1 Samtec QTH-060-03-L-D-A (bottom side)\nimport footprint from Samtec / Antmicro (Apache-2.0)", "bottom")
    b.block(0.0, 8.0, 46.0, 9.0, "J1 keep-out (top): CSI fan-in from the 4 FPCs", "top")
    b.block(-40.0, 4.0, 14.0, 12.0, "U3 RP2040 + flash + XTAL\nJ6 USB-C to Xavier", "top")
    b.block(-40.0, 19.0, 14.0, 8.0, "U4..U8 level shifters\nTRIG / SYNC_OUT / TOUT0", "top")
    b.block(38.0, 4.0, 18.0, 12.0, "U9 12V->5V 4A buck\nU10..U13 5V current-limit sw.", "top")
    b.block(38.0, 19.0, 18.0, 8.0, "J7 12V input\nTVS + rev. polarity", "top")
    b.block(0.0, 21.0, 24.0, 8.0, "U1 TCA9546A + U2 TCA6416A\nI2C pull-ups", "top")
    b.zone("GND", "In1.Cu")
    b.zone("GND", "In4.Cu")
    path = os.path.join(KOUT, "adapter_board.kicad_pcb")
    b.save(path, title="AGX adapter: Xavier camera connector -> 4 x FPC (generated demo)\\n"
                       "Route CSI pairs J2..J5 -> J1 as 100R diff (see hardware/adapter/*.csv)")
    b.preview(os.path.join(KOUT, "layout_preview.png"),
              "AGX adapter board (variant A) - 120 x 56 mm: Xavier QTH-060 -> 4 x FPC-40")
    errs = b.drc()
    print(f"adapter: {len(b.parts)} connectors placed, {len(b.nets)} nets, mini-DRC violations: {len(errs)}")
    print(f"CSVs -> {OUT}")
    raise SystemExit(1 if errs else 0)


if __name__ == "__main__":
    main()
