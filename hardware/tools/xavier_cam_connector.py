"""
Jetson AGX Xavier (and AGX Orin) devkit camera-expansion connector, as seen
from a mezzanine board: Samtec QTH-060-03-L-D-A (2 x 60, 0.5 mm) mating the
devkit's QSH socket.

Pin -> signal map extracted from Antmicro's open-hardware "Jetson AGX CSI
Adapter" (Apache-2.0, github.com/antmicro/jetson-agx-csi-adapter,
interface.kicad_sch) by parsing the schematic's net labels.
Pins marked None are unused/no-connect in that design (they carry other
devkit signals - check the NVIDIA "Jetson AGX Xavier Developer Kit Carrier
Board Specification" (SP-09778) before using them).
"""

SIG = {
    1: "CSI0_D0_P", 2: "CSI1_D0_P", 3: "CSI0_D0_N", 4: "CSI1_D0_N",
    7: "CSI0_CLK_P", 8: "CSI1_CLK_P", 9: "CSI0_CLK_N", 10: "CSI1_CLK_N",
    13: "CSI0_D1_P", 14: "CSI1_D1_P", 15: "CSI0_D1_N", 16: "CSI1_D1_N",
    19: "CSI2_D0_P", 20: "CSI3_D0_P", 21: "CSI2_D0_N", 22: "CSI3_D0_N",
    25: "CSI2_CLK_P", 26: "CSI3_CLK_P", 27: "CSI2_CLK_N", 28: "CSI3_CLK_N",
    31: "CSI2_D1_P", 32: "CSI3_D1_P", 33: "CSI2_D1_N", 34: "CSI3_D1_N",
    37: "CSI4_D0_P", 38: "CSI6_D0_P", 39: "CSI4_D0_N", 40: "CSI6_D0_N",
    43: "CSI4_CLK_P", 44: "CSI6_CLK_P", 45: "CSI4_CLK_N", 46: "CSI6_CLK_N",
    49: "CSI4_D1_P", 50: "CSI6_D1_P", 51: "CSI4_D1_N", 52: "CSI6_D1_N",
    59: "CSI5_D0_P", 60: "CSI7_D0_P", 61: "CSI5_D0_N", 62: "CSI7_D0_N",
    65: "CSI5_CLK_P", 66: "CSI7_CLK_P", 67: "CSI5_CLK_N", 68: "CSI7_CLK_N",
    71: "CSI5_D1_P", 72: "CSI7_D1_P", 73: "CSI5_D1_N", 74: "CSI7_D1_N",
    75: "I2C_GP3_CLK", 77: "I2C_GP3_DAT",            # Tegra cam_i2c = i2c@3180000
    81: "AVDD_CAM_2V8", 82: "AVDD_CAM_2V8", 83: "AVDD_CAM_2V8",
    85: "GPIO10", 92: "CAM1_RST",
    102: "1V8_CONN", 108: "3V3_CONN", 110: "3V3_CONN", 118: "3V3_CONN", 120: "3V3_CONN",
}
GND = [5, 6, 11, 12, 17, 18, 23, 24, 29, 30, 35, 36, 41, 42, 47, 48, 53, 54,
       63, 64, 69, 70, 79, 80, 99, 100, 115, 116]

PINMAP = {p: (SIG.get(p) or ("GND" if p in GND else None)) for p in range(1, 121)}
PINMAP["MP"] = "GND"

# Stereo board k uses the brick pair (2k, 2k+1) as one x4 port:
#   lanes 0,1 = CSI(2k)_D0, CSI(2k)_D1 ; lanes 2,3 = CSI(2k+1)_D0, CSI(2k+1)_D1 ;
#   clock = CSI(2k)_CLK ; CSI(2k+1)_CLK unused.
def fpc_to_xavier(k):
    a, b = 2 * k, 2 * k + 1
    return {
        "AGG_CSI_D0_P": f"CSI{a}_D0_P", "AGG_CSI_D0_N": f"CSI{a}_D0_N",
        "AGG_CSI_D1_P": f"CSI{a}_D1_P", "AGG_CSI_D1_N": f"CSI{a}_D1_N",
        "AGG_CSI_D2_P": f"CSI{b}_D0_P", "AGG_CSI_D2_N": f"CSI{b}_D0_N",
        "AGG_CSI_D3_P": f"CSI{b}_D1_P", "AGG_CSI_D3_N": f"CSI{b}_D1_N",
        "AGG_CSI_CLK_P": f"CSI{a}_CLK_P", "AGG_CSI_CLK_N": f"CSI{a}_CLK_N",
    }


