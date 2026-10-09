/* SPDX-License-Identifier: GPL-2.0 */
/*
 * imx568_mode_tbls.h - Sony IMX568-AAMJ-C register tables
 *
 * Addresses are the I2C (16-bit) addresses. Chip-ID/address pairs from the
 * datasheet map as  I2C = 0x3000 + (chipID - 2) * 0x100 + addr.
 *
 * Every value marked "DS x.y" is taken from IMX568-AAMJ-C Lite Datasheet
 * E21705C2Z, section x.y.
 *
 * !!! The Lite datasheet does NOT contain:
 *   - the "register initial settings" block (section 18 flow step),
 *   - INCK-frequency / PLL / MIPI data-rate selection registers,
 *   - the readout-drive-mode select registers (all-pixel / 2x2 FD binning /
 *     subsampling / ROI) and the per-mode GMRWT/GMTWT/GSDLY values.
 * Those come from the full datasheet / register map / Sony support package
 * (NDA, via Sony or your distributor). Paste them into the IMX568_NDA_*
 * tables below and define IMX568_HAVE_FULL_REGMAP. Without them the driver
 * probes, sequences power, detects the sensor and programs all documented
 * registers, but the sensor will most likely not output a valid image.
 */
#ifndef __IMX568_MODE_TBLS_H__
#define __IMX568_MODE_TBLS_H__

#include <linux/types.h>

#define IMX568_TABLE_WAIT_MS	0xFFFE
#define IMX568_TABLE_END	0xFFFF

/* masked write: reg = (reg & ~mask) | (val & mask); mask 0xFF = plain write */
struct imx568_reg {
	u16 addr;
	u8 val;
	u8 mask;
};

/* ---------------------------------------------------- documented registers */
#define IMX568_STANDBY		0x3000	/* [0] 1=standby (DS 16.1) */
#define IMX568_XMSTA		0x3010	/* [0] 0=master start (DS 16.2) */
#define IMX568_REGHOLD		0x3034	/* [0] 1=hold (DS 16.9) */
#define IMX568_VMAX_L		0x30D4	/* [23:0] lines/frame (DS 16.2) */
#define IMX568_HMAX_L		0x30D8	/* [15:0] 74.25 MHz clocks/line (DS 16.2) */
#define IMX568_GMRWT		0x30E2	/* DS 16.6.1, init 0x06 */
#define IMX568_GMTWT		0x30E3	/* DS 16.6.1, init 0x28 */
#define IMX568_GSDLY		0x30E6	/* DS 16.6.1, init 0x12 */
#define IMX568_ADBIT		0x3200	/* [5:4] 0=10b 1=12b 2=8b (DS 16.7.3) */
#define IMX568_REVERSE		0x3204	/* [0] V, [1] H (DS 16.5) */
#define IMX568_VINT_EN		0x323E	/* [0] trig, [1] normal (DS 16.6) */
#define IMX568_SHS_L		0x3240	/* [23:0] (DS 16.6.1) */
#define IMX568_TRIGMODE		0x3400	/* [2:0] mode, [4:3] TRIGTIMING */
#define IMX568_ODBIT		0x3430	/* [1:0] 0=10b 1=12b 2=8b */
#define IMX568_TOUTSEL12	0x3435
#define IMX568_TOUT0SEL		0x3436	/* [2:0] 1 = exposure monitor */
#define IMX568_SYNCSEL		0x343C	/* [5:4] 0=output 3=Hi-Z */
#define IMX568_GAIN_RTS		0x3502	/* 0x08 this frame / 0x09 next */
#define IMX568_GAIN_L		0x3514	/* [8:0] = dB*10, 0..480 */
#define IMX568_BLKLEVEL_L	0x35B4	/* [11:0] */
#define IMX568_LANESEL		0x3904	/* [2:0] 2=4 lane 3=2 lane */
#define IMX568_MIPI_TIMING	0x3CB4	/* 10 x 16-bit, DS 16.8 */

#define IMX568_TRIGMODE_NORMAL	0x00			/* TRIGMODE 0, TRIGTIMING 0 */
#define IMX568_TRIGMODE_SEQ	(0x01 | (0x1 << 3))	/* slave only */
#define IMX568_TRIGMODE_FAST	(0x02 | (0x1 << 3))	/* master only */

#define IMX568_INCK_HZ		74250000U	/* on-board oscillator */
#define IMX568_TOFFSET_NS	2470U		/* normal-mode exposure offset */
#define IMX568_TOFFSET_FAST_NS	2530U		/* fast-trigger exposure offset */
#define IMX568_GAIN_MAX		480		/* 48.0 dB */

/* --------------------------------------------- MIPI global timing (DS 16.8) */
enum imx568_lane_rate { IMX568_RATE_1188, IMX568_RATE_891, IMX568_RATE_594 };

#define T16(a, v) { (a), (v) & 0xFF, 0xFF }, { (a) + 1, ((v) >> 8) & 0xFF, 0xFF }
#define MIPI_TIMING(prep, cpost, trail, zero, cprep, ctrail, lpx, czero, cpre, exit) \
	T16(0x3CB4, prep), T16(0x3CB6, cpost), T16(0x3CB8, trail), \
	T16(0x3CBA, zero), T16(0x3CBC, cprep), T16(0x3CBE, ctrail), \
	T16(0x3CC0, lpx), T16(0x3CC2, czero), T16(0x3CC4, cpre), T16(0x3CC6, exit)

static const struct imx568_reg imx568_mipi_1188[] = {
	MIPI_TIMING(0x004F, 0x008F, 0x004F, 0x0087, 0x004F, 0x0047, 0x003F, 0x0137, 0x000F, 0x007F),
	{ IMX568_TABLE_END, 0, 0 }
};
static const struct imx568_reg imx568_mipi_891[] = {
	MIPI_TIMING(0x003F, 0x007F, 0x003F, 0x006F, 0x0037, 0x0037, 0x002F, 0x00F7, 0x000F, 0x005F),
	{ IMX568_TABLE_END, 0, 0 }
};
static const struct imx568_reg imx568_mipi_594[] = {
	MIPI_TIMING(0x002F, 0x0067, 0x002F, 0x004F, 0x0027, 0x0027, 0x0027, 0x00B7, 0x000F, 0x0047),
	{ IMX568_TABLE_END, 0, 0 }
};

/* ------------------------------------------------ NDA tables (fill these) */
/*
 * "Register initial settings" from the full datasheet, written once after
 * XCLR release while in standby (DS 18.1 flow). Also put the INCK=74.25 MHz
 * selection here.
 */
static const struct imx568_reg imx568_nda_init[] = {
	/* { 0x3xxx, 0x.., 0xFF },   <-- from Sony register map */
	{ IMX568_TABLE_END, 0, 0 }
};

/* PLL / data-rate setting for 891 Mbps/lane @ INCK 74.25 MHz */
static const struct imx568_reg imx568_nda_rate_891[] = {
	{ IMX568_TABLE_END, 0, 0 }
};

/* readout drive mode select: 2x2 FD binning (1224x1024) */
static const struct imx568_reg imx568_nda_mode_binning[] = {
	{ IMX568_TABLE_END, 0, 0 }
};

/* readout drive mode select: all-pixel (2448x2048) */
static const struct imx568_reg imx568_nda_mode_allpix[] = {
	{ IMX568_TABLE_END, 0, 0 }
};

/* -------------------------------------------------------- common settings */
static const struct imx568_reg imx568_common[] = {
	{ IMX568_ADBIT,      0x1 << 4, 0x30 },	/* 12-bit A/D  (DS 16.7.3) */
	{ IMX568_ODBIT,      0x01,     0x03 },	/* 12-bit out, same as ADBIT */
	{ IMX568_LANESEL,    0x02,     0x07 },	/* 4 lanes (DS 16.7.1) */
	{ IMX568_BLKLEVEL_L, 0xF0,     0xFF },	/* 12-bit recommended 0x0F0 */
	{ IMX568_BLKLEVEL_L + 1, 0x00, 0x0F },
	{ IMX568_GAIN_RTS,   0x08,     0xFF },	/* gain reflected same frame */
	{ IMX568_TOUT0SEL,   0x01,     0x07 },	/* TOUT0 = exposure monitor */
	{ IMX568_TABLE_END, 0, 0 }
};

/* ------------------------------------------------------------ mode list */
struct imx568_mode {
	u32 width, height;
	u32 hmax;		/* 74.25 MHz clocks per line (>= datasheet min) */
	u32 hmax_min;		/* datasheet minimum for this mode/rate */
	u32 vmax;		/* lines per frame (free-run) / tTGPD (trigger) */
	u8 gmrwt, gmtwt;	/* per-mode values: VERIFY with full register list */
	enum imx568_lane_rate rate;
	const struct imx568_reg *nda_mode;
};

enum {
	IMX568_MODE_1224x1024_BIN2_RAW12,
	IMX568_MODE_2448x2048_RAW12,
	IMX568_NUM_MODES
};

/*
 * HMAX is deliberately above the datasheet minimum so that two cameras
 * sharing one MAX9296A x4 port fit the stock L4T deserializer CSI rate
 * (1.2 Gbps/lane x 4 = 4.8 Gbps):
 *   bin2 : 1224 px * 12 b / (600/74.25 MHz) = 1.82 Gbps/cam -> 3.6 Gbps/pair
 *   full : 2448 px * 12 b / (1100/74.25 MHz) = 1.98 Gbps/cam -> 4.0 Gbps/pair
 * Raise the deser PHY rate (DT "imx568,dser-phy-rate-mbps") to use hmax_min.
 * GMTWT: DS 16.6.1 "List of Exposure Setting" gives 30 H (all-pixel) and
 * 56 H (binning) for 1188 Mbps 4-lane 12-bit; GMRWT keeps the reset value.
 */
static const struct imx568_mode imx568_modes[IMX568_NUM_MODES] = {
	[IMX568_MODE_1224x1024_BIN2_RAW12] = {
		.width = 1224, .height = 1024,
		.hmax = 600, .hmax_min = 356, .vmax = 1176,
		.gmrwt = 0x06, .gmtwt = 56,
		.rate = IMX568_RATE_891, .nda_mode = imx568_nda_mode_binning,
	},
	[IMX568_MODE_2448x2048_RAW12] = {
		.width = 2448, .height = 2048,
		.hmax = 1100, .hmax_min = 664, .vmax = 2198,
		.gmrwt = 0x06, .gmtwt = 30,
		.rate = IMX568_RATE_891, .nda_mode = imx568_nda_mode_allpix,
	},
};

static const int imx568_fps_bin2[] = { 30, 60 };
static const int imx568_fps_full[] = { 15, 30 };

static const struct camera_common_frmfmt imx568_frmfmt[] = {
	{ { 1224, 1024 }, imx568_fps_bin2, ARRAY_SIZE(imx568_fps_bin2), 0,
	  IMX568_MODE_1224x1024_BIN2_RAW12 },
	{ { 2448, 2048 }, imx568_fps_full, ARRAY_SIZE(imx568_fps_full), 0,
	  IMX568_MODE_2448x2048_RAW12 },
};

#endif /* __IMX568_MODE_TBLS_H__ */
