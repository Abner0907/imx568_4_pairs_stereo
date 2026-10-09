# Variant B — 4 × MAX9296A deserializer carrier (AGX camera-connector mezzanine)

## 3.1 Blocks

| Block | Part(s) | Notes |
|---|---|---|
| Host connector | Mate for the AGX Xavier devkit camera expansion header (Samtec 120-pin QSH/QTH family) | Take pin assignment from *Jetson AGX Xavier Developer Kit Carrier Board Specification*: CSI A–H (16 lanes + clocks), CAM_I2C, camera GPIOs, 1.8/3.3 V |
| Deserializers | 4 × MAX9296A | DES k → x4 port: A/B, C/D, E/F, G/H. `csi-mode = "2x4"`, port A used, `max-src = 2` |
| I²C | TCA9546A @0x70 on CAM_I2C | One deserializer per channel, so all four can use 0x48 and reuse the same SER/sensor addresses |
| PoC | 2 × MAX20087 (quad camera power protector, I²C) + per-channel PoC inductors | Per-camera enable, current limit and diagnostics. 12 V |
| Coax | 8 × 50 Ω (FAKRA-Z right-angle, or 2 × quad mini-FAKRA) | Label L/R per pair |
| Sync | RP2040 + 2 MB QSPI flash + 12 MHz crystal + USB-C (or header) to Xavier USB | `firmware/sync_controller` |
| Level shift | SN74AXC4T774 (4-bit, 1.8 ↔ 3.3 V) ×2 | TRIG0..3 → DES MFP (DES VDDIO 1.8 V); SYNC_OUT → Xavier GPIO (1.8 V); optional TOUT0 returns → RP2040 |
| Power | 12 V in (≥ 2.5 A) → PoC rail; buck 12 V → 3.3 V; 3.3 V → 1.8 V (DES VDD18/VDDIO); DES core rail per MAX9296A DS (VERIFY) | Do not power 8 cameras from the Xavier header |

## 3.2 Signal list per deserializer k

| MAX9296A function | Net | To |
|---|---|---|
| CSI port A D0–D3 ± , CLK ± | CSIk_D0..3, CSIk_CLK | Xavier brick (2k)/(2k+1). Lane polarity/order fixable via DES lane-map + DT `lane_polarity` |
| SIOA / SIOB | COAX_k_L / COAX_k_R (AC-coupled, PoC injected) | coax connectors |
| PWDNB | CAMk_PWDN | Xavier GPIO (DT `DESk_PWDN_GPIO`) |
| SDA/SCL | mux channel k | TCA9546A |
| MFP (trigger in) | TRIGk_1V8 | RP2040 GP(2+k) via level shifter. Route also to a 2nd MFP through a DNP 0 Ω, in case your DES configuration forwards one GPIO per link |
| MFP (TOUT0 L/R out, optional) | TOUTk_L/R | RP2040 inputs for sync verification |
| LOCK, ERRB | LED + test point | bring-up |
| CFG straps | — | I²C address 0x48, GMSL2 6 Gbps, coax (VERIFY) |

## 3.3 Power budget

8 heads × ≈ 2 W = 16 W of PoC at 12 V (≈ 1.4 A), 4 × MAX9296A (≈ 0.5 W each, VERIFY) and the RP2040 (< 0.2 W). Use a 12 V / 3 A input with reverse-polarity and TVS protection. Set the MAX20087 per-channel current limit to about 300 mA.

## 3.4 Layout notes specific to the carrier

* Xavier side CSI: 100 Ω differential, intra-pair skew < 0.15 mm, length-match lanes within a port to ±0.5 mm. Keep the 4 ports on separate reference regions; no layer change without ground-return vias.
* GMSL coax traces: 50 Ω single-ended CPWG, as short as possible from the DES SIO pin to the connector. Remove the ground plane under the AC-coupling cap and PoC-inductor pads (ADI guidance) to limit discontinuity. Keep the PoC inductor stub short.
* Route the four TRIG lines as equal-length 1.8 V traces. The skew between them adds directly to inter-pair sync error. 1 ns is irrelevant here, but keep them clean and series-terminated (33 Ω at the source).
* Put the RP2040 near the level shifters. SYNC_OUT goes to a Xavier GPIO that has interrupt capability; the `gpiochip:line` is chosen in software.
