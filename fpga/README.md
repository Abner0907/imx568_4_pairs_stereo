# Stereo board FPGA (Lattice CrossLink-NX LIFCL-40)

| File | Purpose |
|---|---|
| `stereo_ctrl.v` | power sequencing (DS 17.1/17.3), XCLR, INCK enable, trigger fan-out/gating, STATUS, aggregator reset |
| `tb_stereo_ctrl.v` | self-checking testbench (rail order, no control while rails down, INCK only after XCLR, L/R trigger identical, abort mid-ramp) |

Run the test:
```bash
iverilog -g2012 -o tb fpga/tb_stereo_ctrl.v fpga/stereo_ctrl.v && vvp tb     # prints PASS
```
Verified here with Icarus Verilog 12.0. A deliberately re-introduced abort bug is caught (rail-order errors).

## Building the bitstream (Lattice Radiant)

1. Download Lattice's **MIPI CSI-2 Virtual Channel Aggregation** reference design for CrossLink-NX and configure it:
   * 2 inputs, RAW12 (data type 0x2C), 4 lanes each, 891 Mbps.
   * Input 0 → VC0 (left), input 1 → VC1 (right).
   * Output 4 lanes, 1.2 Gbps, continuous clock.
2. Add `stereo_ctrl.v` to the top level:
   * `clk` = 74.25 MHz oscillator input.
   * `agg_rst_n` → aggregator reset, so the RX PHYs start only after the sensors run.
   * Map all other ports to I/Os as in `hardware/stereo_board/stereo_board_netlist.csv` (U3 rows).
   * Keep XTRIG_L/XTRIG_R in the same bank with matched board traces.
3. Pin planning:
   * TX → hard D-PHY 0, left RX → hard D-PHY 1, right RX → soft D-PHY in an HP bank.
   * Control I/O in a 1.8 V bank.
4. Program the SPI flash over JTAG. After power-up, the FPGA loads, holds all sensor rails off (EN_* pull-downs), and waits for PWR_EN.

Timing parameters (`T_STEP_US` and others) default to 2 ms rail steps and 5 ms settle. They must exceed the TPS22918 CT ramp; the datasheet requires all rails within 200 ms.
