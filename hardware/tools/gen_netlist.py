#!/usr/bin/env python3
"""
Emit netlists + BOMs as CSV (from imx568_data.py and the off-sensor
connection tables below):

  hardware/stereo_board/      variant A: 2 x IMX568 + CrossLink-NX + FPC (build x4)
  hardware/camera_head_gmsl/  variant B: 1 x IMX568 + MAX9295A (build x8)

  imx568_pin_net*.csv   every IMX568 ball -> board net (exact, from datasheet)
  *_netlist.csv         every component pin -> net.  Non-Sony ICs are listed by
                        *pin function*; map to pin numbers from their own
                        datasheet when capturing the schematic.
  *_bom.csv             grouped BOM
"""
import csv
import os
from collections import Counter

import fpc_pinout
from imx568_data import PINS, DECOUPLING, FILTERS, pin_net

HW = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))

# (ref, part, value/description, [(pin_or_function, net), ...])
SUPPORT = [
    # --- sensor control pins (datasheet 19.4, I2C mode) -----------------------
    ("R1", "R0402", "10R", [("1", "SNS_INCK"), ("2", "OSC_OUT")]),
    ("R2", "R0402", "10R", [("1", "SNS_XCLR"), ("2", "SER_MFP_XCLR")]),
    ("R3", "R0402", "10k", [("1", "SNS_XCLR"), ("2", "GND")]),           # hold reset while SER boots
    ("R4", "R0402", "10R", [("1", "SNS_XTRIG1"), ("2", "SER_MFP_XTRIG")]),
    ("R5", "R0402", "10k", [("1", "SNS_XCE"), ("2", "+1V8_SNS")]),       # XCE high = I2C
    ("R6", "R0402", "10k", [("1", "SNS_SLAMODE"), ("2", "GND")]),        # 1st addr 0x36; 2nd 0x1A always
    ("R7", "R0402", "0R", [("1", "SNS_XMASTER"), ("2", "GND")]),         # master mode (fast trigger)
    ("R8", "R0402", "DNP 0R", [("1", "SNS_XMASTER"), ("2", "+1V8_SNS")]),  # option: slave mode
    ("R9", "R0402", "2k2", [("1", "SNS_SDA"), ("2", "+1V8_SNS")]),
    ("R10", "R0402", "2k2", [("1", "SNS_SCL"), ("2", "+1V8_SNS")]),
    ("R11", "R0402", "10k", [("1", "SNS_XVS"), ("2", "+1V8_SNS")]),
    ("R12", "R0402", "10k", [("1", "SNS_XHS"), ("2", "+1V8_SNS")]),
    ("R13", "R0402", "10R", [("1", "SNS_TOUT0"), ("2", "SER_MFP_TOUT0")]),  # exposure monitor -> host
    ("TP1", "TP", "XVS", [("1", "SNS_XVS")]), ("TP2", "TP", "XHS", [("1", "SNS_XHS")]),
    ("TP3", "TP", "TOUT1", [("1", "SNS_TOUT1")]), ("TP4", "TP", "TOUT2", [("1", "SNS_TOUT2")]),
    ("TP5", "TP", "XTRIG2", [("1", "SNS_XTRIG2")]),                       # leave open (Hi-Z)
    ("TP6", "TP", "TOUT0", [("1", "SNS_TOUT0")]),
    # --- INCK oscillator: OE follows XCLR with ~100 us delay (INCK after XCLR, T5 >= 1 us)
    ("Y1", "SiT8008B 2016 / 1.8 V OE", "74.25 MHz +-50 ppm",
     [("VDD", "+1V8_SNS"), ("GND", "GND"), ("OUT", "OSC_OUT"), ("OE", "OSC_OE")]),
    ("R14", "R0402", "10k", [("1", "SNS_XCLR"), ("2", "OSC_OE")]),
    ("C100", "C0402", "10n", [("1", "OSC_OE"), ("2", "GND")]),
    ("D1", "BAT54 (SOD-523)", "fast OE release", [("A", "OSC_OE"), ("K", "SNS_XCLR")]),
    ("C101", "C0201", "0.1u", [("1", "+1V8_SNS"), ("2", "GND")]),
    # --- GMSL2 serializer ------------------------------------------------------
    ("U2", "MAX9295A (GMSL2 SER, TQFN)", "VERIFY pinout + supplies in MAX9295A DS", [
        ("CSI port: DA0P/DA0N..DA3P/DA3N (lanes 0..3)", "CSI_D0_P/N .. CSI_D3_P/N"),
        ("CSI port: CKP/CKN", "CSI_CLK_P/N"),
        ("SIOP (GMSL coax)", "GMSL_SIO"), ("SION", "GMSL_SION_AC_GND"),
        ("SDA/SCL (I2C to sensor)", "SNS_SDA / SNS_SCL"),
        ("MFP (GPIO RX from DES)", "SER_MFP_XTRIG"),
        ("MFP (GPIO out)", "SER_MFP_XCLR"),
        ("MFP (GPIO out)", "EN_1V1"), ("MFP (GPIO out)", "EN_1V8S"),
        ("MFP (GPIO out)", "EN_2V9"), ("MFP (GPIO out)", "EN_3V3"),
        ("MFP (GPIO TX to DES)", "SER_MFP_TOUT0"),
        ("CFG0/CFG1 straps", "set DEV_ADDR=0x62 (7-bit), coax, GMSL2 6G"),
        ("VDD18 / VDDIO", "+1V8"), ("VDD core", "per DS (int. LDO or ext.)"), ("GND/EP", "GND"),
        ("XRES / PWDNB", "+1V8 via RC"), ("X1/X2", "25 MHz crystal per DS")]),
    ("Y2", "Crystal 25 MHz", "for MAX9295A (per DS)", [("1", "SER_X1"), ("2", "SER_X2")]),
    ("C102", "C0402 (0.1 uF, 50 V)", "SIO AC-coupling", [("1", "GMSL_SIO"), ("2", "J1_CENTER")]),
    ("C103", "C0402 (47 nF)", "SION termination AC cap per DS", [("1", "GMSL_SION_AC_GND"), ("2", "GND")]),
    ("R15", "R0402", "49.9R", [("1", "GMSL_SION_AC_GND"), ("2", "GND")]),
    # --- coax + PoC ------------------------------------------------------------
    ("J1", "Coax jack 50R (FAKRA-Z / mini-FAKRA / HFM)", "",
     [("CENTER", "J1_CENTER"), ("SHIELD", "GND")]),
    ("L10", "PoC inductor (high-Z, e.g. 2.2-10 uH, sized w/ ADI PoC calc.)", "",
     [("1", "J1_CENTER"), ("2", "POC_MID")]),
    ("L11", "PoC ferrite/inductor (2nd stage)", "", [("1", "POC_MID"), ("2", "VPOC")]),
    ("C104", "C1206 25 V", "10u", [("1", "VPOC"), ("2", "GND")]),
    ("D2", "TVS 24 V (SOD-323)", "", [("K", "VPOC"), ("A", "GND")]),
    # --- power -----------------------------------------------------------------
    ("U3", "TPS62160DSG", "12 V -> 3.6 V, 1 A buck",
     [("VIN", "VPOC"), ("EN", "VPOC"), ("SW", "U3_SW"), ("VOS", "+3V6"), ("FB", "U3_FB"),
      ("PG", "PG_3V6"), ("GND", "GND")]),
    ("L3", "2.2 uH 1.5 A", "", [("1", "U3_SW"), ("2", "+3V6")]),
    ("U4", "TLV62569DBV", "3.6 V -> 1.1 V, 2 A buck",
     [("VIN", "+3V6"), ("EN", "PG_3V6"), ("SW", "U4_SW"), ("FB", "U4_FB"), ("GND", "GND")]),
    ("L4", "1.0 uH 2 A", "", [("1", "U4_SW"), ("2", "+1V1_BUCK")]),
    ("U5", "TLV75518PDBV", "1.8 V 500 mA LDO (SER + sensor IO)",
     [("IN", "+3V6"), ("EN", "+3V6"), ("OUT", "+1V8"), ("GND", "GND")]),
    ("U6", "LP5907MFX-2.9", "2.9 V 250 mA low-noise LDO",
     [("IN", "+3V6"), ("EN", "+3V6"), ("OUT", "+2V9_LDO"), ("GND", "GND")]),
    ("U7", "LP5907MFX-3.3", "3.3 V 250 mA low-noise LDO",
     [("IN", "+3V6"), ("EN", "+3V6"), ("OUT", "+3V3_LDO"), ("GND", "GND")]),
    # load switches give the <=25 mV/us slew (CT) and the sequence (ON from SER MFPs)
    ("U8", "TPS22918DBV", "1.1 V switch", [("VIN", "+1V1_BUCK"), ("VOUT", "+1V1"), ("ON", "EN_1V1"),
                                          ("CT", "CT1"), ("QOD", "+1V1"), ("GND", "GND")]),
    ("U9", "TPS22918DBV", "1.8 V switch", [("VIN", "+1V8"), ("VOUT", "+1V8_SNS"), ("ON", "EN_1V8S"),
                                          ("CT", "CT2"), ("QOD", "+1V8_SNS"), ("GND", "GND")]),
    ("U10", "TPS22918DBV", "2.9 V switch", [("VIN", "+2V9_LDO"), ("VOUT", "+2V9"), ("ON", "EN_2V9"),
                                           ("CT", "CT3"), ("QOD", "+2V9"), ("GND", "GND")]),
    ("U11", "TPS22918DBV", "3.3 V switch", [("VIN", "+3V3_LDO"), ("VOUT", "+3V3A"), ("ON", "EN_3V3"),
                                           ("CT", "CT4"), ("QOD", "+3V3A"), ("GND", "GND")]),
    ("C110", "C0402", "1n CT (VERIFY rise time >= V/25mV/us)", [("1", "CT1"), ("2", "GND")]),
    ("C111", "C0402", "1n CT", [("1", "CT2"), ("2", "GND")]),
    ("C112", "C0402", "2.2n CT", [("1", "CT3"), ("2", "GND")]),
    ("C113", "C0402", "2.2n CT", [("1", "CT4"), ("2", "GND")]),
    ("R20", "R0402", "100k", [("1", "EN_1V1"), ("2", "GND")]),     # rails OFF while SER boots
    ("R21", "R0402", "100k", [("1", "EN_1V8S"), ("2", "GND")]),
    ("R22", "R0402", "100k", [("1", "EN_2V9"), ("2", "GND")]),
    ("R23", "R0402", "100k", [("1", "EN_3V3"), ("2", "GND")]),
]


# ------------------------------------------------------------------ variant A
def _pp(prefix, n):
    """prefix sensor-local nets the same way kicadgen.Board.sensor_net does"""
    if n.startswith(("CSI_", "SNS_", "VCP")):
        return f"{prefix}_{n}"
    if n in ("+1V1_LIF", "+1V1_PLA"):
        return f"{n}_{prefix}"
    return n


def _sensor_support(p, slamode_net):
    """per-sensor glue on the stereo board (DS 19.4, I2C mode)"""
    q = lambda n: _pp(p, n)    # noqa: E731
    return [
        (f"R{p}1", "R0402", "22R", [("1", q("SNS_INCK")), ("2", f"INCK_{p}")]),
        (f"R{p}2", "R0402", "10R", [("1", q("SNS_XCLR")), ("2", "FPGA_XCLR")]),
        (f"R{p}3", "R0402", "10R", [("1", q("SNS_XTRIG1")), ("2", f"FPGA_XTRIG_{p}")]),
        (f"R{p}4", "R0402", "10k", [("1", q("SNS_XCE")), ("2", "+1V8_SNS")]),
        (f"R{p}5", "R0402", "10k", [("1", q("SNS_SLAMODE")), ("2", slamode_net)]),
        (f"R{p}6", "R0402", "0R", [("1", q("SNS_XMASTER")), ("2", "GND")]),
        (f"R{p}7", "R0402", "10k", [("1", q("SNS_XVS")), ("2", "+1V8_SNS")]),
        (f"R{p}8", "R0402", "10k", [("1", q("SNS_XHS")), ("2", "+1V8_SNS")]),
        (f"R{p}9", "R0402", "10R", [("1", q("SNS_TOUT0")), ("2", f"TOUT0_{p}")]),
        (f"R{p}10", "R0402", "0R", [("1", q("SNS_SDA")), ("2", "SNS_I2C_SDA")]),
        (f"R{p}11", "R0402", "0R", [("1", q("SNS_SCL")), ("2", "SNS_I2C_SCL")]),
        (f"TP{p}1", "TP", "XVS/XHS/TOUT1/TOUT2/XTRIG2",
         [("1", q("SNS_XVS")), ("2", q("SNS_XHS")), ("3", q("SNS_TOUT1")), ("4", q("SNS_TOUT2")),
          ("5", q("SNS_XTRIG2"))]),
    ]


STEREO_SUPPORT = (
    _sensor_support("L", "GND")            # left : SLAMODE=000 -> 0x36
    + _sensor_support("R", "+1V8_SNS")     # right: SLAMODE=111 -> 0x3D (DS 14.4 table)
    + [
        ("J1", "Hirose FH12-40S-0.5SH(55)", "FPC to AGX adapter (pinout: fpc_pinout.py)",
         [(str(p), n) for p, n in zip(range(1, 41), fpc_pinout.nets())]),
        ("U3", "Lattice LIFCL-40 (CrossLink-NX), caBGA256 (VERIFY package/pinout)",
         "CSI-2 VC aggregation RD (2->1) + fpga/stereo_ctrl.v", [
            ("hard D-PHY #0 TX (4 lanes + clk)", "AGG_CSI_D0..3_P/N, AGG_CSI_CLK_P/N -> J1"),
            ("hard D-PHY #1 RX (4 lanes + clk)", "L_CSI_D0..3_P/N, L_CSI_CLK_P/N  (left, VC0)"),
            ("soft D-PHY RX on HP bank (<=1.5 Gbps/lane)", "R_CSI_D0..3_P/N, R_CSI_CLK_P/N  (right, VC1)"),
            ("clk in (PCLK pin)", "OSC_74M25"), ("pwr_en_in", "PWR_EN"), ("trig_in", "TRIG"),
            ("xtrig_l / xtrig_r", "FPGA_XTRIG_L / FPGA_XTRIG_R (length-matched)"),
            ("xclr", "FPGA_XCLR"), ("inck_oe", "INCK_OE"),
            ("en_1v1/en_1v8/en_2v9/en_3v3", "EN_1V1 / EN_1V8S / EN_2V9 / EN_3V3"),
            ("status", "STATUS"), ("PROGRAMN", "FPGA_PROGRAMN"),
            ("MSPI (dedicated config pins)", "U5 SPI flash"), ("JTAG", "J2"),
            ("VCC 1.0 V / VCCAUX 1.8 V / VCCIO 1.8 V / D-PHY rails", "+1V0_FPGA / +1V8 / +1V8 / per Lattice HW checklist")]),
        ("U4", "TI LMK1C1102 (1:2 LVCMOS buffer w/ OE), VDD 1.8 V", "INCK fan-out",
         [("IN", "OSC_74M25"), ("OE", "INCK_OE"), ("Y0", "INCK_L"), ("Y1", "INCK_R")]),
        ("Y1", "74.25 MHz oscillator, 1.8 V, +-50 ppm (SiT8008-class)", "always on (FPGA ref + INCK)",
         [("VDD", "+1V8"), ("OUT", "OSC_74M25")]),
        ("U5", "W25Q32JW (1.8 V SPI NOR)", "FPGA bitstream", [("SPI", "U3 MSPI")]),
        ("U6", "PCA9306 (I2C translator / isolator)", "bus to sensors only when +1V8_SNS is up",
         [("SCL1/SDA1", "I2C_SCL / I2C_SDA (FPC side)"), ("VREF1", "+1V8"),
          ("SCL2/SDA2", "SNS_I2C_SCL / SNS_I2C_SDA"), ("VREF2/EN", "+1V8_SNS (EN via 200k to VREF2)")]),
        ("R30, R31", "R0402", "2.2k", [("1", "SNS_I2C_SCL / SNS_I2C_SDA"), ("2", "+1V8_SNS")]),
        ("U7", "TPS62162 (3-17 V, 1 A buck)", "VIN_5V -> +3V6", [("VIN", "VIN_5V"), ("VOUT", "+3V6")]),
        ("U8", "TLV62569 (2 A buck)", "+3V6 -> +1V1_BUCK (2 sensors, <= 0.53 A)", [("VIN", "+3V6"), ("VOUT", "+1V1_BUCK")]),
        ("U9", "TLV62569 (2 A buck)", "+3V6 -> +1V0_FPGA (size with Lattice power calculator)", [("VIN", "+3V6"), ("VOUT", "+1V0_FPGA")]),
        ("U10", "TLV75518P (500 mA)", "+3V6 -> +1V8 always-on (FPGA VCCAUX/VCCIO, flash, osc)", [("IN", "+3V6"), ("OUT", "+1V8")]),
        ("U11", "LP5912-3.3 (500 mA low-noise)", "+3V6 -> +3V3_LDO (2 x 45 mA max)", [("IN", "+3V6"), ("OUT", "+3V3_LDO")]),
        ("U12", "500 mA low-noise LDO, 2.9 V (e.g. LP5912 2.9 V option - VERIFY orderable)", "+3V6 -> +2V9_LDO (2 x 125 mA max)",
         [("IN", "+3V6"), ("OUT", "+2V9_LDO")]),
        ("U13..U16", "TPS22918 (CT slew <= 25 mV/us, QOD)", "rail switches, ON from FPGA",
         [("1V1", "+1V1_BUCK -> +1V1, ON=EN_1V1"), ("1V8", "+1V8 -> +1V8_SNS, ON=EN_1V8S"),
          ("2V9", "+2V9_LDO -> +2V9, ON=EN_2V9"), ("3V3", "+3V3_LDO -> +3V3A, ON=EN_3V3")]),
        ("R40..R43", "R0402", "100k pull-down on EN_* (rails off while FPGA configures)", [("x", "EN_*")]),
        ("J2", "2x5 1.27 mm header", "JTAG / SPI programming (Lattice HW-USBN-2B)", [("JTAG", "U3")]),
    ])


def write_board(out, name, sensors, support):
    """sensors: [(ref, prefix)] ; prefix '' = no prefix"""
    os.makedirs(out, exist_ok=True)
    rows, bom = [], Counter()
    for ref, pre in sensors:
        tag = f"_{pre}" if pre else ""
        with open(os.path.join(out, f"imx568_pin_net{tag}.csv"), "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["ball", "pin_name", "kind", "net"])
            for b in sorted(PINS, key=lambda b: (b[0], int(b[1:]))):
                n, k = PINS[b]
                net = pin_net(b)
                w.writerow([b, n, k, (_pp(pre, net) if pre else net) if net else "NO_CONNECT"])
        for b in PINS:
            net = pin_net(b)
            rows.append([ref, "IMX568-AAMJ-C", b, PINS[b][0], (_pp(pre, net) if pre and net else net) or "NO_CONNECT"])
        bom[("U", "IMX568-AAMJ-C", "LGA132")] += 1
    cref = 1
    for ref_s, pre in sensors:
        for e in DECOUPLING:
            rb, caps = e[0], e[2]
            net = pin_net(rb) if rb else e[3]
            net = _pp(pre, net) if pre else net
            for v in caps:
                size = {"1n": "0201", "0.1u": "0201", "1u": "0402", "4.7u": "0402",
                        "10u": "0603", "22u": "0603"}[v]
                ref = f"C{cref}"
                cref += 1
                rows += [[ref, f"C{size} X7R/X5R", "1", "", net], [ref, f"C{size}", "2", "", "GND"]]
                bom[("C", f"{v} {size} X5R/X7R 6.3V+", "")] += 1
        for ref, val, nin, nout, desc in FILTERS:
            nout = _pp(pre, nout) if pre else nout
            rows += [[f"{ref}{pre}", "L0805", "1", "", nin], [f"{ref}{pre}", "L0805", "2", "", nout]]
            bom[("L", f"{val} 0805 >=300 mA, low DCR", desc)] += 1
    for ref, part, val, conns in support:
        for pin, net in conns:
            rows.append([ref, part, pin, "", net])
        bom[(ref[0] if ref[0] not in "UJ" else ref, part, val)] += 1
    with open(os.path.join(out, f"{name}_netlist.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["ref", "part", "pin / function", "imx568_pin_name", "net"])
        w.writerows(rows)
    with open(os.path.join(out, f"{name}_bom.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["group", "part", "value / note", "qty (per board)"])
        for (g, p, v), q in sorted(bom.items()):
            w.writerow([g, p, v, q])
    print(f"{name}: {len(rows)} netlist rows, {sum(bom.values())} parts -> {out}")


def main():
    write_board(os.path.join(HW, "stereo_board"), "stereo_board", [("U1", "L"), ("U2", "R")], STEREO_SUPPORT)
    write_board(os.path.join(HW, "camera_head_gmsl"), "camera_head_gmsl", [("U1", "")], SUPPORT)


if __name__ == "__main__":
    main()
