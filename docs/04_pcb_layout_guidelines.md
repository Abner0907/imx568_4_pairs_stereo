# 4. PCB layout — generated demos and rules

`hardware/tools/gen_kicad.py` generates three KiCad 8 boards. All are 6-layer except the adapter, and each has a `layout_preview.png`:

| Board | Path | Size | What is laid out | Mini-DRC |
|---|---|---|---|---|
| **Stereo pair board** (variant A, ×4) | `hardware/kicad/stereo_board/` | 110 × 36 mm @ 80 mm baseline | 2 × IMX568 with full fan-out + 2 × 81 datasheet passives; 10 CSI-2 pairs routed (100 Ω coupled) from both sensors to the FPGA's sides; FPC-40 with nets; generic BGA-256 for the FPGA; keep-outs for power, clock, flash, JTAG | 0 |
| AGX adapter (variant A) | `hardware/kicad/adapter_board/` (via `gen_adapter.py`) | 120 × 56 mm | 4 × FPC-40 with Xavier nets; keep-outs for QTH-060, mux/expander, RP2040, shifters, power | 0 |
| GMSL camera head (variant B, ×8) | `hardware/kicad/camera_head_gmsl/` | 30 × 30 mm | 1 × IMX568 fan-out + decoupling, CSI via pairs to the serializer keep-out | 0 |

What the sensor part of every demo contains:

* IMX568 LGA-132 with every pad on its net. The origin is the optical centre.
* Dog-bone fan-out: 0.40/0.20 mm vias on the half-grid, a clear diagonal chosen per ball, straps next to the corner lands, no via-in-pad.
* CSI-2 breakout through the lower package edge, tightened to 0.10/0.15 mm coupled pairs.
* All datasheet decoupling (79 caps + 2 × 10 µH per sensor) auto-placed on the back, nearest-first, with short stubs to same-net vias.
* Zones: In1 = GND, In2 = +1V1, In4 = GND. They are unfilled; press **B** in KiCad.

The mini-DRC checks 0.10 mm clearance between different nets on F.Cu, B.Cu and vias. It reports **0 violations** on all three boards.

**These are starting points, not fab-ready boards.** Still to do in KiCad:

1. Replace keep-out blocks with real parts. For the FPGA use Lattice's exact package footprint, then assign D-PHY balls and escape the CSI via pairs into them. Do the same for the regulators, oscillator, LMK1C1102, PCA9306, flash and JTAG. On the adapter, use the Samtec QTH-060-03-L-D-A footprint (Samtec or Antmicro).
2. FPC sockets: run *Tools → Update Footprints from Library*. The footprint ID is KiCad's `Connector_FFC-FPC:Hirose_FH12-40S-0.5SH_1x40-1MP_P0.50mm_Horizontal`; pads keep their nets.
3. Route +3V3A / +2V9 / +1V8_SNS / VCPx on In3, plus the remaining decoupling stubs (ratsnest).
4. Route the aggregated CSI from the FPGA TX to J1, and on the adapter from each FPC to the QTH pins.
5. Run full KiCad DRC with your fab's rules.

## 4.0 Stereo board specifics

* L/R CSI pairs run on F.Cu over the solid GND on In1. Each pair's length is about 30 mm at 80 mm baseline. Match P/N within a pair to ±0.1 mm (the 45° corners add about 0.1 mm to the outer trace; compensate at the FPGA end) and lanes to clock within ±0.5 mm. L vs R need not be matched: the FPGA re-times each input.
* XTRIG_L / XTRIG_R from the FPGA: equal-length traces. Skew here is direct L/R exposure skew; 10 mm ≈ 60 ps, which is negligible but free to get right.
* INCK_L / INCK_R from the LMK1C1102: point-to-point, GND-guarded, away from CSI.
* The aggregated TX pairs (FPGA → J1 on the back) are the highest-rate signals at 1.2 Gbps. Route them shortest, with one layer change max and a GND via per transition.
* Keep the bucks (PWR A block) away from the sensor analog balls and from the sensor CSI. In the demo they sit between the sensors and the FPGA on the back side.
* Board stiffness matters for stereo: use 1.6 mm FR-4, mount on all 5 holes, and keep heavy parts (FPC connector) near a mounting hole.

## 4.1 Stack-up (6 layers, 1.0–1.6 mm)

| Layer | Use |
|---|---|
| L1 F.Cu | Sensor(s), FPGA, CSI routing, fan-out stubs |
| L2 In1 | **Solid GND** (CSI reference). Never split under the CSI pairs |
| L3 In2 | +1V1 plane (largest current, 16 balls per sensor); FPGA +1V0 island under the BGA |
| L4 In3 | +3V3A, +2V9, +1V8_SNS, VCP1/2 fingers; low-speed signals; BGA escape |
| L5 In4 | Solid GND (reference for L6) |
| L6 B.Cu | Decoupling, power, FPC connector (variant A) / serializer + coax (variant B) |

Ask the fab to compute impedance. Typical numbers with 0.09 mm prepreg L1–L2: 100 Ω differential ≈ 0.10 mm width / 0.15 mm gap. Variant B only: the GMSL coax trace is 50 Ω single-ended, coplanar with ground, on L6 referenced to L5.

## 4.2 LGA-132 land pattern and assembly (DS 21, 22)

* Lands: Ø0.60 mm copper (package pad Ø0.6 +0.14/−0), NSMD with 0.05 mm mask expansion. Corner lands 1.6 × 1.6 mm. Paste: Ø0.50 mm (≈ 70 %) on a 0.10 mm stencil; corner lands use a 4-window pane.
* Lite datasheet does not give a recommended land pattern; ask Sony/your assembler before release.
* Vias under the LGA: tented or plugged, not in pads (or use VIPPO if you need via-in-pad).
* **Reflow once only** (DS 21.4 (2b)): peak 240 ± 5 °C, seal-glass resin ≤ 245 °C. Assemble the bottom side first, then the top side with the sensor in the last reflow. Rework of the sensor is not allowed.
* Use within 72 h of opening the moisture barrier (≤ 30 °C / 70 % RH). Bake at most once (125 °C, 24 h).
* **No X-ray inspection on the sensor** (DS 21.4 (3c)). Use AOI and electrical test instead.
* Keep the glass clean (class-1000 or better for lens assembly) and ESD-safe (DS 21.1, 21.2). Do not clamp the package with a rigid load; mount with an elastic load or adhesive (DS 21.3).

## 4.3 Routing rules

* CSI-2: 100 Ω ± 10 % differential, intra-pair skew ≤ 0.1 mm, lane-to-clock length match ±0.5 mm. Reference to the unbroken GND on L2. One layer change maximum, with a GND via next to each pair transition (as in the demo). Keep 3× trace width to other pairs and 5× to switching nodes.
* Decoupling: 0.1 µF / 1 nF 0201 directly under the ball's via, ≤ 1 mm from it. 4.7 µF / 10 µF 0402/0603 within about 3 mm. Bulk 22 µF at the rail entry.
* VDDLPLA and VDDLIF: their 10 µH filters and local caps form small islands. Do not share vias with VDDLSC.
* Keep the buck converters (TPS62160, TLV62569) and their switch nodes on the far side from the sensor's analog balls (columns A–F rows 3–9 carry the 2.9/3.3 V pixel supplies), with solid GND between.
* INCK: short point-to-point, 10 Ω at the source, GND guard. Keep it away from the CSI pairs.
* GMSL: AC cap and PoC inductor right at the SER SIO pin. Void reference copper under those pads (ADI recommendation). The connector's ground pins get several vias straight into L5/L2.

## 4.4 Thermal

The sensor dissipates ≤ 0.86 W. Rated Tj is +100 °C with operation at Topr −30…+75 °C (DS 4); performance is guaranteed only at −10…+60 °C. Use the GND planes plus the corner lands as the heat path and do not put the buck converters under the sensor. The on-chip thermometer (application note) can be read through the driver later.
