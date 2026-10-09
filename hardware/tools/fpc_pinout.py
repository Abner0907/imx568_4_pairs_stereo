"""
40-pin, 0.5 mm FPC between each stereo board and the AGX adapter board.
Connector: Hirose FH12-40S-0.5SH(55) (or equivalent 0.5 mm ZIF) at both ends.

G-S-S-G for every CSI-2 pair; 4 x 5 V supply pins (0.5 A/contact rating,
board needs <= 0.6 A); 1.8 V CMOS for all control signals.
"""

FPC40 = [
    # pin, net (stereo-board side name), description
    (1, "GND", ""),
    (2, "AGG_CSI_D0_P", "aggregated CSI-2 lane 0 + (VC0 = left, VC1 = right)"),
    (3, "AGG_CSI_D0_N", "lane 0 -"),
    (4, "GND", ""),
    (5, "AGG_CSI_D1_P", "lane 1 +"),
    (6, "AGG_CSI_D1_N", "lane 1 -"),
    (7, "GND", ""),
    (8, "AGG_CSI_CLK_P", "clock +"),
    (9, "AGG_CSI_CLK_N", "clock -"),
    (10, "GND", ""),
    (11, "AGG_CSI_D2_P", "lane 2 +"),
    (12, "AGG_CSI_D2_N", "lane 2 -"),
    (13, "GND", ""),
    (14, "AGG_CSI_D3_P", "lane 3 +"),
    (15, "AGG_CSI_D3_N", "lane 3 -"),
    (16, "GND", ""),
    (17, "I2C_SCL", "1.8 V, from adapter mux channel; sensors 0x36 (L, SLAMODE=0) / 0x3D (R, SLAMODE=7)"),
    (18, "I2C_SDA", "1.8 V"),
    (19, "GND", ""),
    (20, "TRIG", "1.8 V, active-low exposure trigger for both sensors (from sync MCU)"),
    (21, "GND", ""),
    (22, "PWR_EN", "1.8 V, high = FPGA powers + releases both sensors"),
    (23, "STATUS", "1.8 V, high = sensors powered, XCLR released, INCK running"),
    (24, "TOUT0_L", "1.8 V, left exposure monitor (sensor TOUT0)"),
    (25, "TOUT0_R", "1.8 V, right exposure monitor"),
    (26, "GND", ""),
    (27, "FPGA_PROGRAMN", "open-drain, low = re-load FPGA bitstream (optional)"),
    (28, "RSVD", "reserved (leave open)"),
    (29, "GND", ""),
    (30, "GND", ""),
    (31, "VIN_5V", "5 V supply"),
    (32, "VIN_5V", "5 V supply"),
    (33, "VIN_5V", "5 V supply"),
    (34, "VIN_5V", "5 V supply"),
    (35, "GND", ""),
    (36, "GND", ""),
    (37, "GND", ""),
    (38, "GND", ""),
    (39, "RSVD", "reserved (leave open)"),
    (40, "GND", ""),
]

assert [p for p, _, _ in FPC40] == list(range(1, 41))


def nets(prefix=""):
    """Net list in pin order; prefix for the adapter side (e.g. 'S0_')."""
    out = []
    for pin, n, _desc in FPC40:
        if n == "GND":
            out.append("GND")
        elif n == "RSVD":
            out.append(f"{prefix}RSVD{pin}")
        else:
            out.append(f"{prefix}{n}")
    return out
