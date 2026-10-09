# 1. System architecture — 4 stereo pairs (8 × IMX568) on Jetson AGX Xavier

## 1.1 Overview

```
            ┌──────────── stereo board k (×4, identical) ─────────────┐
            │  IMX568 L ──CSI x4 891M──► ┐                            │
            │                            ├ CrossLink-NX (LIFCL-40)    │      40-pin FPC (≤ 30 cm)
            │  IMX568 R ──CSI x4 891M──► ┘  VC aggregation 2→1 ───────┼──CSI x4 1.2G (VC0=L, VC1=R)──┐
            │   ▲XTRIG_L ▲XTRIG_R  ◄── stereo_ctrl.v ◄── TRIG ────────┼── I2C, TRIG, PWR_EN, STATUS  │
            │   rails 1V1/1V8/2V9/3V3 + XCLR + INCK sequenced by FPGA │   TOUT0_L/R, 4 × 5 V          │
            └─────────────────────────────────────────────────────────┘                               │
                                                                                                       ▼
 ┌──────────────────────────────── AGX adapter board ───────────────────────────────────────────────────┐
 │ J2..J5 FPC-40 ──► Samtec QTH-060-03-L-D-A (J1) ──► AGX Xavier devkit camera connector (16 CSI lanes)  │
 │ TCA9546A (0x70): one I2C channel per FPC       TCA6416A (0x20): PWR_EN / VIN_EN / STATUS per board    │
 │ RP2040 sync controller: TRIG0..3 → FPC, SYNC_OUT → Xavier GPIO10, USB → Xavier                         │
 │ 12 V in → 5 V / 4 A → 4 × current-limited 5 V switches → FPC VIN_5V                                    │
 └────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

* **4 identical stereo boards** (`hardware/kicad/stereo_board/`, 110 × 36 mm at an 80 mm baseline; `--baseline` sets it). Each holds two IMX568 on one rigid PCB, so the stereo extrinsics stay stable. A CrossLink-NX FPGA merges both sensor streams into **one x4 CSI-2 port**, tagging left as VC0 and right as VC1.
* **One FPC per stereo board** to the **AGX adapter board** (`hardware/kicad/adapter_board/`). The adapter plugs into the AGX Xavier devkit camera connector and routes each FPC to one Xavier x4 brick pair.
* **Why the FPGA is needed:** AGX Xavier accepts at most **6 physical camera streams** (16 lanes), but 36 virtual channels. Eight raw sensors on separate ports is therefore impossible. Four ports × 2 VCs = 8 cameras is supported.
* **Variant B (GMSL2 coax, `docs/variant_b_gmsl/`)** is kept for installations where cameras sit more than ~30 cm from the Xavier. Its driver and device tree are built with `make GMSL=1` / `gen_dtsi.py`.

## 1.2 Xavier mapping

| Stereo board | FPC on adapter | Xavier bricks (lanes 0,1 / 2,3 / clock) | nvcsi port-index | `tegra_sinterface` | VC L / R | /dev/video L / R | I²C bus (mux ch) | Sensor addr L / R |
|---|---|---|---|---|---|---|---|---|
| 0 front | J2 | CSI0_D0,D1 / CSI1_D0,D1 / CSI0_CLK | 0 | serial_a | 0 / 1 | 0 / 1 | i2c-30 (0) | 0x36 / 0x3D |
| 1 rear  | J3 | CSI2 / CSI3 / CSI2_CLK | 2 | serial_c | 0 / 1 | 2 / 3 | i2c-31 (1) | 0x36 / 0x3D |
| 2 left  | J4 | CSI4 / CSI5 / CSI4_CLK | 4 | serial_e | 0 / 1 | 4 / 5 | i2c-32 (2) | 0x36 / 0x3D |
| 3 right | J5 | CSI6 / CSI7 / CSI6_CLK | 6 (vi: 5) | serial_g | 0 / 1 | 6 / 7 | i2c-33 (3) | 0x36 / 0x3D |

The connector pin numbers come from Antmicro's open-hardware AGX CSI adapter (Apache-2.0). They are tabulated in `hardware/adapter/xavier_connector_map.csv` and `hardware/tools/xavier_cam_connector.py`. The left sensor straps SLAMODE = 0 (0x36) and the right strap SLAMODE = 7 (0x3D) (DS 14.4). The common address 0x1A answers on both sensors, so it is never used.

## 1.3 Bandwidth

Sensors run RAW12, 4 lanes at 891 Mbps. The aggregator TX runs 4 lanes at **1.2 Gbps** (4.8 Gbps per FPC). Xavier needs no deskew below 1.5 Gbps.

| Mode | Size | HMAX (min) | 1H | Per sensor (line avg.) | Per stereo board | TX load @ 1.2 G×4 | Free-run max fps |
|---|---|---|---|---|---|---|---|
| 0 (VIO default) | 1224×1024, 2×2 FD binning | 600 (356) | 8.08 µs | 1.82 Gbps | 3.6 Gbps | 76 % | ~105 |
| 1 | 2448×2048 | 1100 (664) | 14.8 µs | 1.98 Gbps | 4.0 Gbps | 83 % | ~30 |

Running the TX at 1.5 Gbps/lane (6.0 Gbps) allows HMAX to drop to the datasheet minimum in mode 1 (~50 fps).

## 1.4 Synchronisation

The sensors run **fast-trigger mode, master** (DS 16.6.3). Exposure starts ≤ 0.1 µs after the XTRIG falling edge and lasts (low width + GMRWT·1H + 2.53 µs).

* The RP2040 PIO generates **one trigger per stereo board**. All four start on the same clock edge (one `irq_force` write). Each pair's pulse is centred so all pairs share the same **mid-exposure** instant, even with different exposures.
* On the stereo board, `stereo_ctrl.v` passes TRIG to XTRIG_L and XTRIG_R combinationally. Left/right skew is only the routing difference (≪ 1 ns), and the gate holds both low until the sensors are powered.
* SYNC_OUT (rising edge = mid-exposure) goes to Xavier **GPIO10** (connector pin 85) and is timestamped with the GPIO uAPI in CLOCK_MONOTONIC. `software/sync_capture` groups the 8 frames of each trigger and stamps the set with that time.
* TOUT0_L/R (exposure monitor) of every sensor return over the FPC. They can be logged by the RP2040 or a scope to prove the sync.

## 1.5 Power

| Consumer | Typ / max |
|---|---|
| IMX568 ×2 (DS 11.2) | 1.0 W / 1.7 W |
| CrossLink-NX + flash + osc + buffer | ≈ 0.3–0.5 W (use Lattice power calculator) |
| Conversion losses | ≈ 0.4 W |
| **Per stereo board** | ≈ 1.8 W / 2.6 W → ≤ 0.55 A at 5 V over 4 FPC contacts |
| **4 boards + adapter** | ≈ 11 W → 12 V / 2 A input |

The 5 V for the boards comes from the adapter's 12 V input, not from the Xavier connector.

## 1.6 Verification status

| Item | Status |
|---|---|
| IMX568 pins, decoupling, power sequence, registers used | From the Lite datasheet; generator asserts 132 pins |
| Stereo board layout demo | 2 sensors fanned out, all datasheet decoupling, 10 CSI pairs routed to the FPGA; **0 mini-DRC violations** |
| AGX connector pinout | Parsed from Antmicro's KiCad schematic (real hardware). Unused pins not identified |
| FPC pinout, adapter netlist | Generated, consistent with DT |
| `stereo_ctrl.v` | **Simulated** with Icarus Verilog 12. Self-checking testbench passes, and a mutation test proves it catches sequencing bugs |
| CSI-2 VC merge | Lattice reference design (not included); needs Radiant + pin planning |
| Driver (FPC and GMSL builds) | Both compile warning-free (`W=1`) with stub NVIDIA headers; not yet on hardware |
| Device trees (FPC, GMSL) | Both compile with dtc; 8 sensor nodes each |
| **Blocking for first image** | IMX568 NDA register tables (PLL/INCK, readout mode, initial settings) |
| **Verify before layout release** | CrossLink-NX package, D-PHY ball assignment, supply rails (Lattice docs); 2.9 V LDO orderable option; level/threshold of TCA6416A-driven switch EN; Xavier GPIO behind CAM1_RST |
