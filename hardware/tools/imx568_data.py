"""
IMX568-AAMJ-C pin / net / decoupling data -- the single source of truth used by
gen_kicad.py (symbol, footprint, layout demo) and gen_netlist.py (CSV netlist + BOM).

Everything here is transcribed from the IMX568-AAMJ-C Lite Datasheet E21705C2Z:
  * pin table           : section 10 (pins 1..132)
  * package geometry    : section 22 (LGA, 132 pins, 15.00 x 12.50 mm, 1.0 mm pitch)
  * reference decoupling: section 19 (19.1 analog, 19.2 digital, 19.3 VCP, 19.4 I/O)

Ball naming: columns A..N (no I), rows 1..12.  In the datasheet "Top View"
(section 7) A1 is at the top-RIGHT and N1 at the top-LEFT, i.e. column A is on
the +X side when looking down on the PCB.
"""

COLUMNS = "ABCDEFGHJKLMN"          # 13 columns, letter I skipped
PITCH = 1.0                        # mm
PKG_W, PKG_H = 15.00, 12.50        # mm (H direction = columns, V direction = rows)

# --------------------------------------------------------------------------
# Pin table: ball -> (name, kind)
#   kind: P=power, G=ground, I=input, O=output, B=bidir, A=analog-ref, N=no-connect,
#         NG = N.C. where "GND connection is allowed" (corner pads + C2)
# --------------------------------------------------------------------------
PINS = {
    # corner pads (1.6 mm square, occupy the A1-B2 style 2x2 grid slots)
    "A1": ("NC_GND", "NG"), "A12": ("NC_GND", "NG"),
    "N1": ("NC_GND", "NG"), "N12": ("NC_GND", "NG"),

    "A3": ("VDDLSC", "P"), "A4": ("VSSLSC", "G"), "A5": ("VDDHDA", "P"),
    "A6": ("VCP2", "A"), "A7": ("VCP1", "A"), "A8": ("VDDHCP", "P"),
    "A9": ("VDDHAN", "P"), "A10": ("VDDLSC", "P"),

    "B3": ("VDDLCN", "P"), "B4": ("VSSLCN", "G"), "B5": ("VSSHDA", "G"),
    "B6": ("VRMTRX", "G"), "B7": ("VSSHCP", "G"), "B8": ("VRLWSS", "G"),
    "B9": ("VSSHAN", "G"), "B10": ("VSSLSC", "G"),

    "C1": ("VSSLSC", "G"), "C2": ("NC_GND", "NG"), "C3": ("VSS33PX", "G"),
    "C4": ("VDD33PX", "P"), "C5": ("VDD33OFD", "P"), "C6": ("VDDLOFD", "P"),
    "C7": ("VDDLTRG", "P"), "C8": ("VDD33PX", "P"), "C9": ("VSS33PX", "G"),
    "C10": ("VSSLIF", "G"), "C11": ("NC", "N"), "C12": ("NC", "N"),

    "D1": ("VDDLSC", "P"), "D2": ("XTRIG2", "I"), "D3": ("VRLSEL", "A"),
    "D4": ("VRLTRX", "A"), "D5": ("VRLOFG", "A"), "D6": ("VRLTRY", "A"),
    "D7": ("VRLFDB", "A"), "D8": ("VRLTRG", "A"), "D9": ("VRLRST", "G"),
    "D10": ("VSSLIF", "G"), "D11": ("NC", "N"), "D12": ("NC", "N"),

    "E1": ("XVS", "B"), "E2": ("XTRIG1", "I"), "E3": ("VDD33TRX", "P"),
    "E4": ("VDD33SEL", "P"), "E5": ("VDD33OFG", "P"), "E6": ("VDD33TRY", "P"),
    "E7": ("VDD33FDB", "P"), "E8": ("VDD33TRG", "P"), "E9": ("VDD33RST", "P"),
    "E10": ("VSSLIF", "G"), "E11": ("DOM3", "O"), "E12": ("DOP3", "O"),

    "F1": ("VSSLSC", "G"), "F2": ("NC", "N"), "F3": ("VSSHCM", "G"),
    "F4": ("VDDHCM", "P"), "F9": ("VSS33PX", "G"), "F10": ("VDDLIF", "P"),
    "F11": ("DOM1", "O"), "F12": ("DOP1", "O"),

    "G1": ("VDDLSC", "P"), "G2": ("VSSLSC", "G"), "G3": ("VSSLCB", "G"),
    "G4": ("VDDLCB", "P"), "G9": ("NC", "N"), "G10": ("VSSLSC", "G"),
    "G11": ("DCKM", "O"), "G12": ("DCKP", "O"),

    "H1": ("SDA", "B"), "H2": ("SLAMODE1", "I"), "H3": ("NC", "N"),
    "H4": ("NC", "N"), "H9": ("NC", "N"), "H10": ("VDDLSC", "P"),
    "H11": ("DOM0", "O"), "H12": ("DOP0", "O"),

    "J1": ("SDO", "O"), "J2": ("XCLR", "I"), "J3": ("VSS33PX", "G"),
    "J4": ("VDD33PX", "P"), "J5": ("VDDLCB", "P"), "J6": ("VSSHAN", "G"),
    "J7": ("VDD33SUB", "P"), "J8": ("VDD33PX", "P"), "J9": ("VSS33PX", "G"),
    "J10": ("VSSLIF", "G"), "J11": ("DOM2", "O"), "J12": ("DOP2", "O"),

    "K1": ("VSSLSC", "G"), "K2": ("SLAMODE0", "I"), "K3": ("VSSHCM", "G"),
    "K4": ("VDDHCM", "P"), "K5": ("VSSLCB", "G"), "K6": ("NC", "N"),
    "K7": ("NC", "N"), "K8": ("NC", "N"), "K9": ("NC", "N"),
    "K10": ("VDDLIF", "P"), "K11": ("NC", "N"), "K12": ("NC", "N"),

    "L1": ("VDDLSC", "P"), "L2": ("SLAMODE2", "I"), "L3": ("XMASTER", "I"),
    "L4": ("VSSLPL", "G"), "L5": ("VDDLPL", "P"), "L6": ("VSSLPLA", "G"),
    "L7": ("VDDLPLA", "P"), "L8": ("VSSLPLA", "G"), "L9": ("VDDLPLA", "P"),
    "L10": ("VSSLIF", "G"), "L11": ("NC", "N"), "L12": ("NC", "N"),

    "M3": ("VDDLCN", "P"), "M4": ("VSSLCN", "G"), "M5": ("TOUT0", "O"),
    "M6": ("TOUT2", "O"), "M7": ("TOUT1", "O"), "M8": ("VSSLPLD", "G"),
    "M9": ("VDDLPLD", "P"), "M10": ("VSSLSC", "G"),

    "N3": ("VDDLSC", "P"), "N4": ("VSSLSC", "G"), "N5": ("XHS", "B"),
    "N6": ("SCL", "I"), "N7": ("XCE", "I"), "N8": ("INCK", "I"),
    "N9": ("VDDMIO", "P"), "N10": ("VDDLSC", "P"),
}

CORNER_PADS = ("A1", "A12", "N1", "N12")


def ball_xy(ball):
    """Pad centre in mm, footprint origin = package centre = optical centre,
    KiCad convention (+X right, +Y down), viewed from the TOP of the PCB."""
    col, row = ball[0], int(ball[1:])
    c = COLUMNS.index(col)
    if ball in CORNER_PADS:
        # corner pad sits in the middle of its 2x2 grid slot (e.g. A1/B1/A2/B2)
        c = c + 0.5 if c == 0 else c - 0.5
        row = row + 0.5 if row == 1 else row - 0.5
    x = (6 - c) * PITCH          # column A at +6 mm, column N at -6 mm
    y = (row - 6.5) * PITCH      # row 1 at -5.5 mm, row 12 at +5.5 mm
    return round(x, 3), round(y, 3)


# --------------------------------------------------------------------------
# Board nets.  Pin name -> net on the camera head board.
# --------------------------------------------------------------------------
PIN_NET = {
    # 1.1 V digital (DVDD). G4/J5/C6/C7 are analog pins that the datasheet
    # explicitly allows to share the digital rail (section 19.2 note).
    "VDDLSC": "+1V1", "VDDLCN": "+1V1", "VDDLCB": "+1V1", "VDDLTRG": "+1V1",
    "VDDLOFD": "+1V1", "VDDLPL": "+1V1", "VDDLPLD": "+1V1",
    "VDDLIF": "+1V1_LIF",          # behind 10 uH (section 19.2)
    "VDDLPLA": "+1V1_PLA",         # behind 10 uH (section 19.2)
    # 1.8 V interface (OVDD)
    "VDDMIO": "+1V8_SNS",
    # 2.9 V analog (AVDD2)
    "VDDHCM": "+2V9", "VDDHAN": "+2V9", "VDDHDA": "+2V9", "VDDHCP": "+2V9",
    # 3.3 V analog (AVDD1)
    "VDD33PX": "+3V3A", "VDD33SUB": "+3V3A", "VDD33OFD": "+3V3A",
    "VDD33OFG": "+3V3A", "VDD33RST": "+3V3A", "VDD33SEL": "+3V3A",
    "VDD33TRG": "+3V3A", "VDD33TRX": "+3V3A", "VDD33TRY": "+3V3A",
    "VDD33FDB": "+3V3A",
    # internal charge-pump outputs (section 19.3)
    "VCP1": "VCP1", "VRLTRG": "VCP1",
    "VCP2": "VCP2", "VRLSEL": "VCP2", "VRLTRX": "VCP2", "VRLOFG": "VCP2",
    "VRLTRY": "VCP2", "VRLFDB": "VCP2",
    # MIPI CSI-2 (section 16.7.2: DOP0/DOM0 = lane 1 ... DOP3/DOM3 = lane 4)
    "DOP0": "CSI_D0_P", "DOM0": "CSI_D0_N", "DOP1": "CSI_D1_P", "DOM1": "CSI_D1_N",
    "DOP2": "CSI_D2_P", "DOM2": "CSI_D2_N", "DOP3": "CSI_D3_P", "DOM3": "CSI_D3_N",
    "DCKP": "CSI_CLK_P", "DCKM": "CSI_CLK_N",
    # control (section 19.4)
    "SDA": "SNS_SDA", "SCL": "SNS_SCL", "XCE": "SNS_XCE", "SDO": "NC_SDO",
    "SLAMODE0": "SNS_SLAMODE", "SLAMODE1": "SNS_SLAMODE", "SLAMODE2": "SNS_SLAMODE",
    "XMASTER": "SNS_XMASTER", "XCLR": "SNS_XCLR", "INCK": "SNS_INCK",
    "XTRIG1": "SNS_XTRIG1", "XTRIG2": "SNS_XTRIG2",
    "XVS": "SNS_XVS", "XHS": "SNS_XHS",
    "TOUT0": "SNS_TOUT0", "TOUT1": "SNS_TOUT1", "TOUT2": "SNS_TOUT2",
    "NC_GND": "GND",
}


def pin_net(ball):
    name, kind = PINS[ball]
    if kind == "G":
        return "GND"
    if kind == "N":
        return None                      # leave open (datasheet section 10 note)
    if name == "SDO":
        return None                      # I2C mode: SDO open (section 19.4)
    return PIN_NET[name]


# --------------------------------------------------------------------------
# Decoupling per datasheet section 19.  Each entry: (ref_ball, gnd_ball, [caps])
# ref_ball is the supply ball the cap must sit next to; gnd_ball its return.
# Bulk caps use ref_ball=None (place near the rail entry).
# --------------------------------------------------------------------------
DECOUPLING = [
    # 3.3 V pixel supply: 0.1 uF per VDD33PX/VSS33PX pair + 2x22 uF bulk
    ("C8", "C9", ["0.1u"]), ("J8", "F9", ["0.1u"]), ("C4", "J9", ["0.1u"]),
    ("J4", "C3", ["0.1u"]),
    (None, None, ["22u", "22u"], "+3V3A"),
    # every other 3.3 V pin: 0.1 uF + 10 uF
    ("E7", None, ["0.1u", "10u"]), ("C5", None, ["0.1u", "10u"]),
    ("E5", None, ["0.1u", "10u"]), ("E9", None, ["0.1u", "10u"]),
    ("E4", None, ["0.1u", "10u"]), ("E8", None, ["0.1u", "10u"]),
    ("E3", None, ["0.1u", "10u"]), ("E6", None, ["0.1u", "10u"]),
    # 2.9 V
    ("F4", "F3", ["0.1u"]), ("K4", "K3", ["0.1u"]), (None, None, ["22u"], "+2V9"),
    ("A9", "B9", ["0.1u", "4.7u"]), ("A5", "B5", ["4.7u", "0.1u"]),
    ("A8", "B7", ["0.1u", "0.1u", "0.1u", "1u", "1u", "1u"]),
    # 1.1 V VDDLSC: 4.7 uF + 0.1 uF per pair, 22 uF bulk
    ("A3", "A4", ["4.7u", "0.1u"]), ("A10", "B10", ["4.7u", "0.1u"]),
    ("D1", "C1", ["4.7u", "0.1u"]), ("G1", "F1", ["4.7u", "0.1u"]),
    ("H10", "G10", ["4.7u", "0.1u"]), ("L1", "K1", ["4.7u", "0.1u"]),
    ("N10", "M10", ["4.7u", "0.1u"]), ("N3", "N4", ["4.7u", "0.1u"]),
    (None, None, ["22u"], "+1V1"),
    # VDDLCN: 0.1 + 4.7 per pin, 22 uF bulk
    ("B3", "B4", ["0.1u", "4.7u"]), ("M3", "M4", ["0.1u", "4.7u"]),
    (None, None, ["22u"], "+1V1"),
    # VDDLCB: 0.1 per pin + 1 uF
    ("G4", "G3", ["0.1u"]), ("J5", "K5", ["0.1u"]), (None, None, ["1u"], "+1V1"),
    # VDDLPL, VDDLTRG, VDDLOFD
    ("L5", "L4", ["4.7u", "0.1u"]), ("C7", None, ["0.1u", "4.7u"]),
    ("C6", None, ["0.1u", "4.7u"]),
    # VDDLPLA (behind 10 uH): 4.7 + 0.1 + 0.001
    ("L7", "L6", ["4.7u", "0.1u", "1n"]),
    # VDDLPLD: 0.1 + 0.001
    ("M9", "M8", ["0.1u", "1n"]),
    # VDDLIF (behind 10 uH): 0.1 + 0.001
    ("F10", "C10", ["0.1u", "1n"]),
    # VDDMIO
    ("N9", None, ["1u", "0.1u"]),
    # charge pumps: 2 x 4.7 uF each
    ("A7", None, ["4.7u", "4.7u"]), ("A6", None, ["4.7u", "4.7u"]),
]

# Ferrite / inductor filters (section 19.2)
FILTERS = [
    ("L1", "10uH", "+1V1", "+1V1_LIF", "VDDLIF filter"),
    ("L2", "10uH", "+1V1", "+1V1_PLA", "VDDLPLA filter"),
]

if __name__ == "__main__":
    assert len(PINS) == 132, len(PINS)
    names = sorted({n for n, _ in PINS.values()})
    print(f"{len(PINS)} pins, {len(names)} unique names")
    nets = {}
    for b in PINS:
        nets.setdefault(pin_net(b), []).append(b)
    for n in sorted(nets, key=str):
        print(f"{str(n):12s} {len(nets[n]):3d}  {' '.join(sorted(nets[n]))}")
