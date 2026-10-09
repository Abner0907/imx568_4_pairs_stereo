# IMX568 4-stereo-pair VIO camera system for Jetson AGX Xavier

Four hardware-synchronized stereo pairs (8 × Sony IMX568-AAMJ-C, 5.1 MP mono global shutter):

* **4 identical stereo boards.** Each carries two IMX568 on a rigid 80 mm baseline (configurable). A CrossLink-NX FPGA merges left/right into one x4 CSI-2 port (VC0/VC1).
* **4 FPC cables** (40-pin, 0.5 mm) run to an **AGX adapter board**. It plugs into the Xavier devkit camera connector (Samtec QTH-060) and uses all 16 CSI lanes.
* **An RP2040 sync controller** on the adapter triggers each pair. All pairs share a common mid-exposure, and a SYNC_OUT edge timestamps every 8-frame set on the Xavier.

Variant B (GMSL2 coax heads + MAX9296A carrier) is kept for camera runs longer than ~30 cm.

```
docs/
  01_system_architecture.md     overview, Xavier lane/VC/I2C map, bandwidth, sync, power, verification status
  02_stereo_board_design.md     stereo board: sensors, FPGA, power, clock, mechanics
  03_fpc_and_xavier_adapter.md  FPC pinout/spec, AGX connector pin map, adapter circuits + layout rules
  04_pcb_layout_guidelines.md   the 3 generated layouts, stack-up, LGA assembly, routing rules
  05_bringup_and_sync.md        build/install, bring-up checklist, sync proof, VIO timestamps
  variant_b_gmsl/               GMSL2 camera head + deserializer carrier (long cables)
hardware/
  tools/imx568_data.py          single source of truth: 132-pin table, nets, datasheet decoupling
  tools/kicadgen.py             KiCad board generator library (fan-out, decoupling, routing, mini-DRC, preview)
  tools/gen_kicad.py            -> symbol, footprint, stereo_board, camera_head_gmsl  (--baseline mm)
  tools/gen_adapter.py          -> adapter_board + hardware/adapter/*.csv
  tools/gen_netlist.py          -> hardware/stereo_board/*.csv, hardware/camera_head_gmsl/*.csv
  tools/fpc_pinout.py           40-pin FPC pinout
  tools/xavier_cam_connector.py AGX camera connector pin map (from Antmicro, Apache-2.0)
  kicad/                        IMX568.kicad_sym, IMX568.pretty/, stereo_board/, adapter_board/, camera_head_gmsl/
  stereo_board/ adapter/ camera_head_gmsl/   netlists, pin maps, BOMs (CSV)
fpga/                           stereo_ctrl.v (sequencing/trigger/status) + simulated testbench
driver/
  kernel/nv_imx568.c            tegracam driver: default = stereo board/FPC, `make GMSL=1` = variant B
  kernel/imx568_mode_tbls.h     register tables (documented regs filled; NDA tables to fill)
  dts/gen_dtsi_fpc.py           -> tegra194-camera-imx568-fpc-8cam.dtsi  (variant A)
  dts/gen_dtsi.py               -> tegra194-camera-imx568-gmsl-8cam.dtsi (variant B)
firmware/sync_controller/       RP2040 PIO trigger generator (per-pair exposure, common mid-exposure, SYNC_OUT)
software/sync_capture/          C++17 V4L2 + GPIO capture -> synchronized 8-frame sets (+ unit test)
```

Regenerate everything:
```bash
python3 hardware/tools/gen_kicad.py --baseline 80   # exit 1 on any mini-DRC violation
python3 hardware/tools/gen_adapter.py
python3 hardware/tools/gen_netlist.py
python3 driver/dts/gen_dtsi_fpc.py && python3 driver/dts/gen_dtsi.py
```

## Status

| Part | State |
|---|---|
| Stereo board layout demo | 2 sensors fully fanned out + decoupled, 10 CSI pairs routed to the FPGA; 0 mini-DRC violations |
| Adapter | Xavier connector map (from proven open hardware), FPC↔Xavier netlist, layout demo with the 4 FPC sockets |
| FPGA control logic | Simulated with Icarus Verilog: testbench passes, mutation test caught |
| CSI-2 VC merge | Lattice reference design (to configure in Radiant) |
| Driver | FPC and GMSL builds compile warning-free (`W=1`) against kernel headers with stub NVIDIA headers; not yet run on hardware |
| Device trees | Both compile with dtc (8 sensors) |
| Sync firmware / capture tool | Firmware type-checked (no Pico SDK here); tool builds, unit test passes |
| **Blocking for first image** | IMX568 NDA register tables (PLL/INCK, readout mode, initial settings) |
| **Verify before layout release** | CrossLink-NX package + D-PHY ball assignment + supply rails; 2.9 V LDO option; 1.8 V EN compatibility of the 5 V switches; Xavier GPIO behind CAM1_RST/GPIO10 |

The IMX568 datasheet in this folder is marked **Confidential** (Sony). Keep it, and anything copied from it, out of public repositories.
