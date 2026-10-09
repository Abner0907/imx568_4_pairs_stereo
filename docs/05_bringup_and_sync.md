# 5. Bring-up and sync verification (AGX Xavier, JetPack 5.1.x / L4T R35.x)

## 5.0 Before the first power-up

1. **Fill the IMX568 NDA tables** in `driver/kernel/imx568_mode_tbls.h`: `imx568_nda_init`, `imx568_nda_rate_891`, `imx568_nda_mode_binning` and `imx568_nda_mode_allpix`. Also check per-mode GMRWT/GMTWT. These come from the full IMX568 datasheet or register map. Then build with `-DIMX568_HAVE_FULL_REGMAP`.
2. **FPGA:** build the Lattice VC-aggregation design plus `fpga/stereo_ctrl.v` (`fpga/README.md`) and program each stereo board's SPI flash over JTAG.
3. **Device tree:** in `driver/dts/tegra194-camera-imx568-fpc-8cam.dtsi`, check `ADAPTER_EXP_RESET_GPIO`, the Tegra GPIO behind connector pin 92 (CAM1_RST).

## 5.1 Build and install

```bash
# driver (variant A, default) - on the Jetson with nvidia-l4t-kernel-headers
cd driver/kernel && make EXTRA_CFLAGS=-DIMX568_HAVE_FULL_REGMAP && sudo make install
#   variant B (GMSL):  make GMSL=1 ...

# device tree: in your board dts (e.g. tegra194-p2888-0001-p2822-0000.dts)
#   #include "tegra194-camera-imx568-fpc-8cam.dtsi"     (variant A)
#   #include "tegra194-camera-imx568-gmsl-8cam.dtsi"    (variant B)
# and disable other camera overlays that use i2c@3180000 / nvcsi; rebuild + flash the dtb.

# capture tool
cd software/sync_capture && cmake -B build && cmake --build build -j && ./build/test_assembler
```

## 5.2 Step-by-step (variant A)

| Step | Check | Expected |
|---|---|---|
| 1 | Adapter on the devkit, 12 V applied, no FPCs | 5 V switches off (VIN_EN low until Linux sets them) |
| 2 | `sudo i2cdetect -y -r 2` (the bus of `i2c@3180000`, check with `i2cdetect -l`) | 0x20 (TCA6416A), 0x70 (TCA9546A) |
| 3 | Connect one stereo board; boot | `vin-stereoK` regulators on → FPGA configures (DONE LED). `/sys/kernel/debug/regulator/regulator_summary` shows vin-stereo0..3 |
| 4 | `dmesg \| grep imx568` | `IMX568 @0x36 ready (stereo board / FPC, fast-trigger)` and `@0x3d` for each board |
| 5 | Scope on one board while starting a stream | 1V1 → 1V8 → 2V9 → 3V3 in 2 ms steps, each ramp ≥ 0.15 ms; XCLR, then INCK; STATUS high |
| 6 | Free-run test of one pair: set `imx568,sync-mode = "master";` on both nodes of board 0, then `v4l2-ctl -d /dev/video0 --set-ctrl bypass_mode=0 --set-fmt-video=width=1224,height=1024,pixelformat=RG12 --stream-mmap --stream-count=300` (and video1) | ~30 fps each. VC0/VC1 split by the FPGA works |
| 7 | Flash the RP2040 (`firmware/sync_controller`), USB to the Xavier | `/dev/ttyACM0`; `STATUS` → `OK …` |
| 8 | Scope TRIG0 at the adapter, XTRIG at both sensors of board 0 | Identical edges; L/R skew < 1 ns; adapter → sensor delay constant (FPC + FPGA, ~10 ns) |
| 9 | `imx568_sync_capture --mode 0 --fps 30 --exposure-us 4000 --sync-tty /dev/ttyACM0 --sync-gpio <gpiochip>:<GPIO10 line> --seconds 20` | `sets 30.0/s (… partial 0, late frames 0)`, all 8 cameras at 30 fps |

`--sync-gpio` needs the gpiochip and line of the Tegra GPIO behind connector pin 85 (GPIO10); `gpioinfo` lists it. The latency from SYNC_OUT to sensor in variant A is only the level shifter + FPC + FPGA path (tens of ns). The mid-exposure timestamp therefore needs no correction beyond the GPIO interrupt latency, which the kernel timestamps in hard-IRQ context.

## 5.3 Proving the synchronisation

1. **Electrical:** route the TOUT0_L/R monitor lines (exposure windows, `TOUT0SEL = 1`) of all 8 sensors to the RP2040 or a logic analyser. Every window should be centred on SYNC_OUT, and pairs with different exposures share the centre.
2. **Optical:** point all cameras at a fast LED counter. With exposure ≤ 100 µs, all 8 images of a set must show the same code.
3. **Software:** the tool's `max SOF spread` should stay at about (E_max − E_min)/2 plus a few tens of µs. If frames go late or partial, the period is too short for exposure + readout (`MINPER`).

## 5.4 Timestamps and VIO

* `FrameSet::t_mid_ns` = CLOCK_MONOTONIC of the SYNC_OUT edge, which is the mid-exposure of all 8 images.
* Put the IMU on the same time base. Either let the RP2040 sample it, or use an IMU with an external-sync input driven by SYNC_OUT. Calibrate camera–IMU time offset and extrinsics with Kalibr, and the 4 stereo pairs' intrinsics/extrinsics with `kalibr_calibrate_cameras`.
* L4T exposes RAW12 as `RG12`. Read it as mono Y12; on Xavier it is MSB-aligned in 16 bits, hence `--shift 4`. Verify with a test pattern.

## 5.5 Known limitations

* In fast-trigger mode the sync controller owns exposure and frame rate (`EXP k <us>` per stereo pair, `FPS`). V4L2 exposure/frame-rate controls act only in `master` mode.
* Both sensors of a stereo board power up and down together, because the regulator is shared and refcounted. A stream on one sensor keeps the other powered (in standby).
* Variant B only: the stock L4T MAX9296 driver handles RAW12 and a 1.2 Gbps PHY; see `docs/variant_b_gmsl/`.
