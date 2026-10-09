#!/usr/bin/env python3
"""
Generate the KiCad 8 artefacts:

  hardware/kicad/IMX568.kicad_sym, IMX568.pretty/IMX568_LGA132.kicad_mod
  hardware/kicad/stereo_board/stereo_board.kicad_pcb (+ .kicad_pro, preview PNG)
        Variant A (primary): one board = one stereo pair, 2 x IMX568 on a rigid
        baseline, CrossLink-NX VC aggregator, 40-pin FPC to the AGX adapter.
        Build 4 of them for the 4 pairs.
  hardware/kicad/camera_head_gmsl/camera_head_gmsl.kicad_pcb (+ ...)
        Variant B (long cables): single camera head with MAX9295A over coax.

Usage:  python3 gen_kicad.py [--baseline 80]
Exit code 1 if the mini-DRC finds a clearance violation.
"""
import argparse
import os

import fpc_pinout
from imx568_data import PINS
from kicadgen import Board, bga_footprint, footprint_body, fpc_footprint

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, "..", "kicad"))


# =================================================================== symbol
def pin_etype(kind):
    return {"P": "power_in", "G": "power_in", "I": "input", "O": "output",
            "B": "bidirectional", "A": "passive", "N": "no_connect", "NG": "passive"}[kind]


def gen_symbol():
    def f(v):
        return f"{v:.2f}".rstrip("0").rstrip(".")
    sig_l = ["INCK", "XCLR", "XCE", "SCL", "SDA", "SDO", "SLAMODE0", "SLAMODE1",
             "SLAMODE2", "XMASTER", "XTRIG1", "XTRIG2", "XVS", "XHS"]
    sig_r = ["DCKP", "DCKM", "DOP0", "DOM0", "DOP1", "DOM1", "DOP2", "DOM2", "DOP3", "DOM3",
             "TOUT0", "TOUT1", "TOUT2", "VCP1", "VRLTRG", "VCP2", "VRLSEL", "VRLTRX", "VRLOFG",
             "VRLTRY", "VRLFDB"]
    by_name = {}
    for ball, (name, kind) in PINS.items():
        by_name.setdefault(name, []).append(ball)

    def pin(etype, x, y, ang, name, num):
        return (f'      (pin {etype} line (at {f(x)} {f(y)} {ang}) (length 2.54)\n'
                f'        (name "{name}" (effects (font (size 1.27 1.27))))\n'
                f'        (number "{num}" (effects (font (size 1.27 1.27)))))\n')

    u1, W1, y = [], 22.86, 22.86
    for n in sig_l:
        for b in by_name[n]:
            u1.append(pin(pin_etype(PINS[b][1]), -W1 - 2.54, y, 0, n, b)); y -= 2.54
    yl, y = y, 22.86
    for n in sig_r:
        for b in sorted(by_name[n]):
            u1.append(pin(pin_etype(PINS[b][1]), W1 + 2.54, y, 180, n, b)); y -= 2.54
    y = min(yl, y) - 2.54
    x = -W1 + 2.54
    for b in sorted(b for b, (n, k) in PINS.items() if k == "N"):
        u1.append(pin("no_connect", x, y - 2.54, 90, "NC", b)); x += 2.54
    u1_box = (-W1, 25.4, W1, y)

    pw = sorted((b for b, (n, k) in PINS.items() if k == "P"), key=lambda b: (PINS[b][0], b))
    gd = sorted((b for b, (n, k) in PINS.items() if k in ("G", "NG")), key=lambda b: (PINS[b][0], b))
    u2, W2 = [], 15.24
    y = (max(len(pw), len(gd)) * 2.54) / 2
    top = y + 2.54
    for b in pw:
        u2.append(pin("power_in", -W2 - 2.54, y, 0, PINS[b][0], b)); y -= 2.54
    yb, y = y, top - 2.54
    for b in gd:
        u2.append(pin(pin_etype(PINS[b][1]), W2 + 2.54, y, 180,
                      PINS[b][0] if PINS[b][0] != "NC_GND" else "NC(GND)", b)); y -= 2.54
    u2_box = (-W2, top, W2, min(yb, y))

    def rect(b):
        return (f'      (rectangle (start {f(b[0])} {f(b[1])}) (end {f(b[2])} {f(b[3])})\n'
                f'        (stroke (width 0.254) (type default)) (fill (type background)))\n')
    s = ['(kicad_symbol_lib (version 20231120) (generator "imx568_gen") (generator_version "8.0")\n',
         '  (symbol "IMX568-AAMJ-C" (pin_names (offset 1.016)) (exclude_from_sim no) (in_bom yes) (on_board yes)\n',
         '    (property "Reference" "U" (at 0 27.94 0) (effects (font (size 1.27 1.27))))\n',
         '    (property "Value" "IMX568-AAMJ-C" (at 0 -30 0) (effects (font (size 1.27 1.27))))\n',
         '    (property "Footprint" "IMX568:IMX568_LGA132" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))\n',
         '    (property "Datasheet" "IMX568-AAMJ-C Lite Datasheet E21705C2Z" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))\n',
         '    (property "Description" "Sony Pregius S 5.1MP mono global-shutter CMOS, LGA132, MIPI CSI-2 2/4 lane" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))\n',
         '    (symbol "IMX568-AAMJ-C_1_1"\n', rect(u1_box), *u1, '    )\n',
         '    (symbol "IMX568-AAMJ-C_2_1"\n', rect(u2_box), *u2, '    )\n',
         '  )\n)\n']
    assert sum(x.count("(pin ") for x in u1 + u2) == 132
    path = os.path.join(OUT, "IMX568.kicad_sym")
    with open(path, "w") as fh:
        fh.write("".join(s))
    return path


def gen_footprint():
    os.makedirs(os.path.join(OUT, "IMX568.pretty"), exist_ok=True)
    s = ('(footprint "IMX568_LGA132" (version 20240108) (generator "imx568_gen") (generator_version "8.0") (layer "F.Cu")\n'
         '  (descr "Sony IMX568-AAMJ-C LGA-132, 15.00x12.50 mm, 1.0 mm pitch, 128x phi0.6 + 4x 1.6 mm corner lands. '
         'Origin = package centre = optical centre. Verify land/paste against Sony recommended pattern + assembler.")\n'
         '  (tags "LGA132 Sony Pregius IMX568 image sensor")\n' + footprint_body() + ')\n')
    path = os.path.join(OUT, "IMX568.pretty", "IMX568_LGA132.kicad_mod")
    with open(path, "w") as fh:
        fh.write(s)
    return path


# ============================================== Variant A: stereo pair board
def gen_stereo_board(baseline):
    if baseline < 50:
        raise SystemExit("baseline must be >= 50 mm (FPGA + routing between the sensors)")
    W, H = baseline + 30.0, 36.0
    b = Board("stereo_board", W, H)
    xl, xr, ys = -baseline / 2, baseline / 2, -3.0

    # --- holes: 4 corners, 2 per lens holder (22 mm), 1 centre-top
    for x in (-W / 2 + 3, W / 2 - 3):
        for y in (-H / 2 + 3, H / 2 - 3):
            b.hole(x, y)
    for xc in (xl, xr):
        b.hole(xc - 11, ys)
        b.hole(xc + 11, ys)
    b.hole(0, -H / 2 + 3)

    # --- fixed blocks (keep-outs) before auto-placement
    fpga_y = 5.0
    b.block(0, fpga_y - 1.0, 16.0, 14.0, "U3 FPGA decoupling\n(per Lattice HW checklist)", "bottom")
    b.block(0, -11.0, 10.0, 6.0, "Y1 74.25 MHz 1V8\n+ LMK1C1102 (OE)\nINCK_L / INCK_R", "top")
    b.block(-baseline / 2 + 21.5, 9.0, 9.0, 12.0, "PWR A\n5V->3V6 (TPS62162)\n3V6->1V1 (TLV62569)\n1V0 FPGA core", "bottom")
    b.block(baseline / 2 - 21.5, 9.0, 9.0, 12.0, "PWR B\nLDO 1V8/2V9/3V3\nTPS22918 x4\n(seq. by FPGA)", "bottom")
    b.block(-15.0, -11.0, 8.0, 6.0, "U5 SPI flash\nW25Q32JW (1V8)", "bottom")
    b.block(15.0, -11.0, 8.0, 6.0, "J2 JTAG/SPI prog\n+ PCA9306 I2C iso", "bottom")

    # --- FPC to the AGX adapter (bottom side, lower edge)
    fpc_footprint(b, "J1", 0.0, 13.2, fpc_pinout.nets(), side="bottom")

    # --- FPGA (CrossLink-NX LIFCL-40, 256-ball caBGA 0.8 mm) on top
    bga_footprint(b, "U3", "LIFCL-40 caBGA256", 0.0, fpga_y, n=16, pitch=0.8, ball_pad=0.40,
                  note="assign D-PHY balls per Lattice pinout")

    # --- the two sensors (prefix L / R) with fan-out + decoupling
    pl = b.imx568("U1", xl, ys, "L")
    pr = b.imx568("U2", xr, ys, "R")

    # --- CSI-2 from each sensor to the FPGA's sides (F.Cu, 100R pairs)
    rows = [ys + 7.6 + i * 1.0 for i in range(5)]
    ends_l = [-(8.6 + (i % 2) * 1.2) for i in range(5)]
    ends_r = [(8.6 + (i % 2) * 1.2) for i in range(5)]
    b.route_pairs_to(pl, rows, ends_l, +1)
    b.route_pairs_to(pr, rows, ends_r, -1)

    b.zone("GND", "In1.Cu")
    b.zone("+1V1", "In2.Cu")
    b.zone("GND", "In4.Cu")
    title = (f"IMX568 stereo pair board - baseline {baseline:g} mm (generated, build x4)\\n"
             "6L: F=sensors/FPGA/CSI | In1=GND | In2=+1V1 | In3=3V3A/2V9/1V8 + FPGA rails | In4=GND | B=decoupling, power, FPC\\n"
             "To finish: FPGA D-PHY ball assignment + escape, aggregated CSI to J1, power blocks, fill zones, KiCad DRC")
    path = os.path.join(OUT, "stereo_board", "stereo_board.kicad_pcb")
    b.save(path, title=title)
    b.preview(os.path.join(OUT, "stereo_board", "layout_preview.png"),
              f"Stereo pair board (variant A, FPC) - {W:g} x {H:g} mm, baseline {baseline:g} mm, 6 layers")
    return b


# ============================================== Variant B: GMSL camera head
def gen_camera_head_gmsl():
    b = Board("camera_head", 30.0, 30.0)
    for x, y, w, h, label in [
            (0.0, 11.6, 5.6, 5.6, "U2 MAX9295A\nGMSL2 SER\n(TQFN 5x5)"),
            (-9.6, -9.6, 9.0, 9.0, "J1 COAX\n(vertical mini-FAKRA/HFM)\n+ PoC filter"),
            (9.0, -9.8, 10.0, 8.0, "POWER\nTPS62160 12V->3V6\nTLV62569 ->1V1\nLDO 1V8/2V9/3V3"),
            (9.6, 9.6, 9.0, 7.0, "LOAD SW x4\nTPS22918 (CT slew)\n+ seq. via SER MFP"),
            (-10.0, 6.0, 4.0, 3.0, "Y1 74.25MHz\nOSC 1V8")]:
        b.block(x, y, w, h, label, "bottom")
    for (hx, hy) in [(-12.5, -12.5), (12.5, -12.5), (-12.5, 12.5), (12.5, 12.5), (-11.0, 0.0), (11.0, 0.0)]:
        b.hole(hx, hy)
    pairs = b.imx568("U1", 0.0, 0.0, "")
    # staggered via pairs into the serializer area (B.Cu escape left to the designer)
    for i, p in enumerate(sorted(pairs, key=lambda p: p["cx"])):
        yv, sp, c, h = (7.4 if i % 2 == 0 else 8.3), 0.30, p["cx"], p["half"]
        for net, dx, sx in ((p["P"], -h, -sp), (p["N"], h, sp)):
            b.path([(c + dx, p["y"]), (c + dx, yv - 0.4), (c + sx, yv)], p["w"], "F.Cu", net)
            b.via(c + sx, yv, net)
        b.via(c, yv + 0.55, "GND")
    b.zone("GND", "In1.Cu")
    b.zone("+1V1", "In2.Cu")
    b.zone("GND", "In4.Cu")
    path = os.path.join(OUT, "camera_head_gmsl", "camera_head_gmsl.kicad_pcb")
    b.save(path, title="IMX568 GMSL2 camera head (variant B) - generated layout demo")
    b.preview(os.path.join(OUT, "camera_head_gmsl", "layout_preview.png"),
              "GMSL2 camera head (variant B, coax) - 30 x 30 mm, 6 layers")
    return b


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", type=float, default=80.0, help="stereo baseline in mm (>= 50)")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    print(gen_symbol())
    print(gen_footprint())
    bad = 0
    for name, fn in (("stereo_board", lambda: gen_stereo_board(a.baseline)),
                     ("camera_head_gmsl", gen_camera_head_gmsl)):
        brd = fn()
        errs = brd.drc()
        for e in errs[:20]:
            print("  DRC", *e)
        print(f"{name}: {len(brd.vias)} vias, {len(brd.tracks)} tracks, {len(brd.parts)} parts, "
              f"{len(brd.nets)} nets, mini-DRC violations: {len(errs)}")
        bad += len(errs)
    raise SystemExit(1 if bad else 0)
