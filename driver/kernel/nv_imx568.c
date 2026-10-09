// SPDX-License-Identifier: GPL-2.0
/*
 * nv_imx568.c - Sony IMX568 (Pregius S, 5.1 MP mono global shutter) for
 *               NVIDIA Jetson (tegracam, L4T R35.x / AGX Xavier; builds on R36).
 *
 * Two board topologies (compile time):
 *
 *  A) default - stereo pair board over FPC (hardware/kicad/stereo_board):
 *       IMX568 L --CSI x4--> CrossLink-NX VC aggregator --CSI x4 (VC0 L, VC1 R)--> FPC --> Tegra
 *       IMX568 R --CSI x4--^
 *     Both sensors share the board rails. The FPGA sequences them when the
 *     board's PWR_EN goes high; Linux sees that as a shared, ref-counted
 *     regulator ("vdd-stereo-supply", a regulator-fixed on the adapter's
 *     TCA6416A). STATUS (optional "status-gpios") reports READY.
 *     I2C: left 0x36 (SLAMODE=0), right 0x3D (SLAMODE=7) behind the TCA9546A.
 *
 *  B) make GMSL=1 - single camera head over GMSL2 (MAX9295A -> MAX9296A),
 *     rails/XCLR driven through the serializer MFPs (L4T gmsl-link framework).
 *
 * Synchronisation (both): fast-trigger mode, master (DS 16.6.3). Exposure
 * starts <= 0.1 us after the falling edge of XTRIG1 and lasts
 * (XTRIG low width + GMRWT * 1H + 2.53 us); the trigger is generated per
 * stereo pair by the sync controller, which therefore owns exposure and frame
 * rate. V4L2 exposure / frame-rate controls act only in "master" (free-run)
 * mode, intended for single-camera bring-up.
 *
 * Copyright (c) 2026.  GMSL part follows the structure of NVIDIA's nv_imx390.c (GPL-2.0).
 */
#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/i2c.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/of_device.h>
#include <linux/regmap.h>
#include <linux/regulator/consumer.h>
#include <linux/slab.h>
#include <linux/version.h>

#ifdef IMX568_GMSL
#include <media/max9295.h>
#include <media/max9296.h>
#endif
#include <media/tegracam_core.h>

#include "imx568_mode_tbls.h"

#ifndef IMX568_HAVE_FULL_REGMAP
#warning "IMX568: NDA register tables are empty - see imx568_mode_tbls.h"
#endif

enum imx568_sync_mode { IMX568_SYNC_FAST_TRIGGER, IMX568_SYNC_MASTER };

static const u32 ctrl_cid_list[] = {
	TEGRA_CAMERA_CID_GAIN,
	TEGRA_CAMERA_CID_EXPOSURE,
	TEGRA_CAMERA_CID_FRAME_RATE,
	TEGRA_CAMERA_CID_SENSOR_MODE_ID,
};

#ifdef IMX568_GMSL
/* MAX9295A / MAX96717 GPIO block: 3 registers per MFP starting at 0x2BE
 * (layout matches the upstream Linux max96717 driver). */
#define SER_GPIO_A(n)		(0x2BE + 3 * (n))
#define SER_GPIO_B(n)		(0x2BF + 3 * (n))
#define SER_GPIO_C(n)		(0x2C0 + 3 * (n))
#define SER_GPIO_OUT		BIT(4)
#define SER_GPIO_RX_EN		BIT(2)
#define SER_GPIO_TX_EN		BIT(1)
#define SER_GPIO_OUT_DIS	BIT(0)
#define SER_GPIO_ID_MASK	0x1F
#define SER_NUM_MFP		11
/* MAX9296A BACKTOP22: [5] DPLL override enable, [4:0] rate in 100 Mbps */
#define DES_PHY_CSI_TX_DPLL	0x320
enum { EN_1V1, EN_1V8, EN_2V9, EN_3V3, EN_NUM };
#endif

struct imx568 {
	struct i2c_client		*i2c_client;
	struct v4l2_subdev		*subdev;
	struct camera_common_data	*s_data;
	struct tegracam_device		*tc_dev;
	enum imx568_sync_mode		sync_mode;
	bool				rail_on;

	/* topology A */
	struct regulator		*vdd;		/* shared stereo-board power */
	struct gpio_desc		*status_gpio;	/* board READY, optional */
	u32				ready_timeout_ms;

#ifdef IMX568_GMSL
	/* topology B */
	struct device			*ser_dev;
	struct device			*dser_dev;
	struct regmap			*ser_map;
	struct regmap			*dser_map;
	struct gmsl_link_ctx		g_ctx;
	u32				mfp_en[EN_NUM];
	u32				mfp_xclr;
	u32				mfp_xtrig;
	u32				mfp_tout0;	/* SER_NUM_MFP = unused */
	u32				gpio_id_trig;
	u32				gpio_id_tout0;
	u32				dser_phy_mbps;	/* 0 = keep L4T default */
	u16				*dser_regs;	/* addr/val pairs */
	int				n_dser_regs;
#endif

	const struct imx568_mode	*mode;
	u32				line_ns;	/* 1H in ns */
	u32				frame_lines;	/* VMAX in use */
	u32				exposure_us;	/* last requested */
};

static const struct regmap_config sensor_regmap_config = {
	.reg_bits = 16,
	.val_bits = 8,
	.cache_type = REGCACHE_NONE,	/* rails are switched: never cache */
};

#ifdef IMX568_GMSL
static struct mutex serdes_lock__;
#endif

/* ------------------------------------------------------------ register io */
static inline int imx568_read_reg(struct camera_common_data *s_data, u16 addr, u8 *val)
{
	u32 v = 0;
	int err = regmap_read(s_data->regmap, addr, &v);

	*val = v & 0xFF;
	return err;
}

static int imx568_write_reg(struct camera_common_data *s_data, u16 addr, u8 val)
{
	int err = regmap_write(s_data->regmap, addr, val);

	if (err)
		dev_err(s_data->dev, "i2c write 0x%04x=0x%02x failed (%d)\n", addr, val, err);
	return err;
}

static int imx568_write_table(struct imx568 *priv, const struct imx568_reg *t)
{
	struct regmap *map = priv->s_data->regmap;
	int err;

	for (; t->addr != IMX568_TABLE_END; t++) {
		if (t->addr == IMX568_TABLE_WAIT_MS) {
			usleep_range(t->val * 1000, t->val * 1000 + 500);
			continue;
		}
		if (t->mask == 0xFF)
			err = regmap_write(map, t->addr, t->val);
		else
			err = regmap_update_bits(map, t->addr, t->mask, t->val);
		if (err) {
			dev_err(&priv->i2c_client->dev, "table write 0x%04x failed\n", t->addr);
			return err;
		}
	}
	return 0;
}

/* little-endian multi-byte register (Sony: LSB at lowest address) */
static int imx568_write_le(struct imx568 *priv, u16 addr, u32 val, int bytes)
{
	int i, err;

	for (i = 0; i < bytes; i++) {
		err = imx568_write_reg(priv->s_data, addr + i, (val >> (8 * i)) & 0xFF);
		if (err)
			return err;
	}
	return 0;
}

#ifndef IMX568_GMSL
/* ============================================================ power: topology A */
/*
 * The stereo-board FPGA (fpga/stereo_ctrl.v) implements DS 17.1 / 17.3:
 * 1V1 -> 1V8 -> 2V9 -> 3V3, XCLR release, INCK start, then STATUS=1 and the
 * trigger is passed to both sensors. The regulator is shared by the L and R
 * sensor nodes, so it only switches off when both are idle.
 */
static int imx568_board_power(struct imx568 *priv, bool on)
{
	struct device *dev = &priv->i2c_client->dev;
	unsigned long deadline;
	int err;

	if (on == priv->rail_on)
		return 0;
	if (!on) {
		priv->rail_on = false;
		return regulator_disable(priv->vdd);
	}
	err = regulator_enable(priv->vdd);	/* startup-delay-us covers the FPGA ramp */
	if (err)
		return err;
	priv->rail_on = true;
	if (!priv->status_gpio)
		return 0;
	deadline = jiffies + msecs_to_jiffies(priv->ready_timeout_ms);
	while (gpiod_get_value_cansleep(priv->status_gpio) <= 0) {
		if (time_after(jiffies, deadline)) {
			dev_err(dev, "stereo board STATUS not ready after %u ms\n", priv->ready_timeout_ms);
			regulator_disable(priv->vdd);
			priv->rail_on = false;
			return -ETIMEDOUT;
		}
		usleep_range(1000, 2000);
	}
	return 0;
}

#endif

#ifdef IMX568_GMSL
/* ============================================================ power: topology B */
static int ser_mfp_out(struct imx568 *priv, u32 mfp, bool high)
{
	if (mfp >= SER_NUM_MFP)
		return 0;
	return regmap_update_bits(priv->ser_map, SER_GPIO_A(mfp),
				  SER_GPIO_OUT | SER_GPIO_RX_EN | SER_GPIO_TX_EN | SER_GPIO_OUT_DIS,
				  high ? SER_GPIO_OUT : 0);
}

/* output driven by the GMSL GPIO with ID @id coming from the deserializer */
static int ser_mfp_rx(struct imx568 *priv, u32 mfp, u32 id)
{
	int err;

	if (mfp >= SER_NUM_MFP)
		return 0;
	err = regmap_update_bits(priv->ser_map, SER_GPIO_C(mfp), SER_GPIO_ID_MASK, id);
	if (err)
		return err;
	return regmap_update_bits(priv->ser_map, SER_GPIO_A(mfp),
				  SER_GPIO_RX_EN | SER_GPIO_TX_EN | SER_GPIO_OUT_DIS, SER_GPIO_RX_EN);
}

/* input forwarded to the deserializer as GMSL GPIO @id */
static int ser_mfp_tx(struct imx568 *priv, u32 mfp, u32 id)
{
	int err;

	if (mfp >= SER_NUM_MFP)
		return 0;
	err = regmap_update_bits(priv->ser_map, SER_GPIO_B(mfp), SER_GPIO_ID_MASK, id);
	if (err)
		return err;
	return regmap_update_bits(priv->ser_map, SER_GPIO_A(mfp),
				  SER_GPIO_RX_EN | SER_GPIO_TX_EN | SER_GPIO_OUT_DIS,
				  SER_GPIO_TX_EN | SER_GPIO_OUT_DIS);
}

static int imx568_rails(struct imx568 *priv, bool on)
{
	static const int order_on[EN_NUM] = { EN_1V1, EN_1V8, EN_2V9, EN_3V3 };
	int i, err;

	for (i = 0; i < EN_NUM; i++) {
		int r = on ? order_on[i] : order_on[EN_NUM - 1 - i];

		err = ser_mfp_out(priv, priv->mfp_en[r], on);
		if (err)
			return err;
		usleep_range(2000, 2500);	/* > CT-controlled ramp time */
	}
	return 0;
}

static int imx568_head_power(struct imx568 *priv, bool on)
{
	int err;

	if (!on) {
		/* DS 17.3: inputs to 0 V before OVDD falls, then 3V3->2V9->1V8->1V1 */
		ser_mfp_out(priv, priv->mfp_xtrig, false);
		ser_mfp_out(priv, priv->mfp_xclr, false);
		usleep_range(200, 300);
		priv->rail_on = false;
		return imx568_rails(priv, false);
	}
	err = ser_mfp_out(priv, priv->mfp_xclr, false);
	err = err ?: ser_mfp_out(priv, priv->mfp_xtrig, false);
	err = err ?: imx568_rails(priv, true);
	if (err)
		return err;
	usleep_range(1000, 1500);		/* T_LOW >= 0.5 us */
	err = ser_mfp_out(priv, priv->mfp_xclr, true);
	usleep_range(1000, 1500);		/* OSC OE RC + T_XCE >= 20 us */
	if (!err && priv->sync_mode == IMX568_SYNC_FAST_TRIGGER)
		err = ser_mfp_rx(priv, priv->mfp_xtrig, priv->gpio_id_trig);
	else if (!err)
		err = ser_mfp_out(priv, priv->mfp_xtrig, true);
	if (!err && priv->mfp_tout0 < SER_NUM_MFP)
		err = ser_mfp_tx(priv, priv->mfp_tout0, priv->gpio_id_tout0);
	priv->rail_on = !err;
	return err;
}
#endif

/* ============================================================ power: common */
static int imx568_power_on(struct camera_common_data *s_data)
{
	struct camera_common_power_rail *pw = s_data->power;
	struct imx568 *priv = (struct imx568 *)s_data->priv;
	int err = 0;

	if (priv) {
#ifdef IMX568_GMSL
		if (priv->ser_map)
			err = imx568_head_power(priv, true);
#else
		if (priv->vdd)
			err = imx568_board_power(priv, true);
#endif
	}
	if (err) {
		dev_err(s_data->dev, "power on failed (%d)\n", err);
		return err;
	}
	pw->state = SWITCH_ON;
	return 0;
}

static int imx568_power_off(struct camera_common_data *s_data)
{
	struct camera_common_power_rail *pw = s_data->power;
	struct imx568 *priv = (struct imx568 *)s_data->priv;

	if (priv && priv->rail_on) {
#ifdef IMX568_GMSL
		imx568_head_power(priv, false);
#else
		imx568_board_power(priv, false);
#endif
	}
	pw->state = SWITCH_OFF;
	return 0;
}

static int imx568_power_get(struct tegracam_device *tc_dev)
{
	/* INCK comes from the on-board oscillator, rails from the board: nothing to get here */
	tc_dev->s_data->power->state = SWITCH_OFF;
	return 0;
}

static int imx568_power_put(struct tegracam_device *tc_dev)
{
	return tc_dev->s_data->power ? 0 : -EFAULT;
}

/* ------------------------------------------------------------ controls */
static int imx568_set_group_hold(struct tegracam_device *tc_dev, bool val)
{
	return imx568_write_reg(tc_dev->s_data, IMX568_REGHOLD, val ? 1 : 0);
}

static int imx568_set_gain(struct tegracam_device *tc_dev, s64 val)
{
	/* DT gain_factor = 10  ->  val is already dB * 10 = register value */
	u32 g = clamp_t(s64, val, 0, IMX568_GAIN_MAX);

	dev_dbg(tc_dev->dev, "gain %u.%u dB\n", g / 10, g % 10);
	return imx568_write_le(tegracam_get_privdata(tc_dev), IMX568_GAIN_L, g, 2);
}

static int imx568_apply_shutter(struct imx568 *priv)
{
	const struct imx568_mode *m = priv->mode;
	u64 lines;
	u32 shs, min_shs = m->gmtwt + 4, max_shs = priv->frame_lines - 1;

	/* DS 16.6.1: exp = 1H * (lines_per_frame - SHS) + 2.47 us */
	lines = priv->exposure_us > 3 ? ((u64)priv->exposure_us * 1000 - IMX568_TOFFSET_NS) : 0;
	lines = div_u64(lines + priv->line_ns / 2, priv->line_ns);
	shs = lines >= priv->frame_lines ? min_shs : priv->frame_lines - (u32)lines;
	shs = clamp(shs, min_shs, max_shs);
	return imx568_write_le(priv, IMX568_SHS_L, shs, 3);
}

static int imx568_set_exposure(struct tegracam_device *tc_dev, s64 val)
{
	struct imx568 *priv = tegracam_get_privdata(tc_dev);
	struct camera_common_data *s_data = tc_dev->s_data;
	const struct sensor_mode_properties *mp =
		&s_data->sensor_props.sensor_modes[s_data->mode_prop_idx];
	u32 factor = mp->control_properties.exposure_factor ?: 1000000;

	priv->exposure_us = (u32)div_u64((u64)val * 1000000, factor);
	if (priv->sync_mode == IMX568_SYNC_FAST_TRIGGER || !priv->mode)
		return 0;	/* exposure = XTRIG pulse width (sync controller) */
	return imx568_apply_shutter(priv);
}

static int imx568_set_frame_rate(struct tegracam_device *tc_dev, s64 val)
{
	struct imx568 *priv = tegracam_get_privdata(tc_dev);
	struct camera_common_data *s_data = tc_dev->s_data;
	const struct sensor_mode_properties *mp =
		&s_data->sensor_props.sensor_modes[s_data->mode_prop_idx];
	u32 factor = mp->control_properties.framerate_factor ?: 1000000;
	u64 frame_ns, lines;

	if (val <= 0 || priv->sync_mode == IMX568_SYNC_FAST_TRIGGER || !priv->mode)
		return 0;	/* frame rate = trigger rate */
	frame_ns = div64_u64((u64)factor * 1000000000ULL, (u64)val);
	lines = div_u64(frame_ns, priv->line_ns);
	priv->frame_lines = max_t(u32, (u32)min_t(u64, lines, 0xFFFFFF), priv->mode->vmax);
	return imx568_write_le(priv, IMX568_VMAX_L, priv->frame_lines, 3) ?:
	       imx568_apply_shutter(priv);
}

static struct tegracam_ctrl_ops imx568_ctrl_ops = {
	.numctrls = ARRAY_SIZE(ctrl_cid_list),
	.ctrl_cid_list = ctrl_cid_list,
	.set_gain = imx568_set_gain,
	.set_exposure = imx568_set_exposure,
	.set_frame_rate = imx568_set_frame_rate,
	.set_group_hold = imx568_set_group_hold,
};

/* ------------------------------------------------------------ mode / stream */
static int imx568_set_mode(struct tegracam_device *tc_dev)
{
	struct imx568 *priv = tegracam_get_privdata(tc_dev);
	struct camera_common_data *s_data = tc_dev->s_data;
	const struct imx568_reg *mipi;
	const struct imx568_mode *m;
	int err;

	if (s_data->mode_prop_idx < 0 || s_data->mode_prop_idx >= IMX568_NUM_MODES)
		return -EINVAL;
	m = &imx568_modes[s_data->mode_prop_idx];
	priv->mode = m;
	priv->line_ns = (u32)div_u64((u64)m->hmax * 1000000000ULL, IMX568_INCK_HZ);
	priv->frame_lines = m->vmax;

	mipi = m->rate == IMX568_RATE_1188 ? imx568_mipi_1188 :
	       m->rate == IMX568_RATE_891 ? imx568_mipi_891 : imx568_mipi_594;

	/* sensor is in standby here (power-on default, or after stop) */
	err = imx568_write_table(priv, imx568_nda_init);
	err = err ?: imx568_write_table(priv, imx568_nda_rate_891);
	err = err ?: imx568_write_table(priv, m->nda_mode);
	err = err ?: imx568_write_table(priv, imx568_common);
	err = err ?: imx568_write_table(priv, mipi);
	err = err ?: imx568_write_le(priv, IMX568_HMAX_L, m->hmax, 2);
	err = err ?: imx568_write_le(priv, IMX568_VMAX_L, m->vmax, 3);
	err = err ?: imx568_write_reg(s_data, IMX568_GMRWT, m->gmrwt);
	err = err ?: imx568_write_reg(s_data, IMX568_GMTWT, m->gmtwt);
	if (priv->sync_mode == IMX568_SYNC_FAST_TRIGGER) {
		/* DS 16.6.3: TRIGMODE=2 must be set in standby; master mode only */
		err = err ?: imx568_write_reg(s_data, IMX568_TRIGMODE, IMX568_TRIGMODE_FAST);
	} else {
		err = err ?: imx568_write_reg(s_data, IMX568_TRIGMODE, IMX568_TRIGMODE_NORMAL);
		err = err ?: imx568_apply_shutter(priv);
	}
	if (err)
		return err;

	dev_info(&priv->i2c_client->dev,
		 "mode %ux%u RAW12, 1H=%u ns, VMAX=%u, %s; exposure = XTRIG_low + %u ns\n",
		 m->width, m->height, priv->line_ns, m->vmax,
		 priv->sync_mode == IMX568_SYNC_FAST_TRIGGER ? "fast-trigger" : "free-run",
		 m->gmrwt * priv->line_ns + IMX568_TOFFSET_FAST_NS);
	return 0;
}

static int imx568_start_streaming(struct tegracam_device *tc_dev)
{
	struct imx568 *priv = tegracam_get_privdata(tc_dev);
	int err;

#ifdef IMX568_GMSL
	struct device *dev = tc_dev->dev;

	mutex_lock(&serdes_lock__);
	err = max9295_setup_streaming(priv->ser_dev);
	err = err ?: max9296_setup_streaming(priv->dser_dev, dev);
	if (!err && priv->dser_phy_mbps)
		err = regmap_write(priv->dser_map, DES_PHY_CSI_TX_DPLL,
				   0x20 | (priv->dser_phy_mbps / 100));
	err = err ?: max9296_start_streaming(priv->dser_dev, dev);
	mutex_unlock(&serdes_lock__);
	if (err) {
		dev_err(dev, "serdes streaming setup failed (%d)\n", err);
		return err;
	}
#endif
	err = imx568_write_reg(priv->s_data, IMX568_STANDBY, 0x00);
	if (err)
		return err;
	usleep_range(7000, 8000);		/* internal regulators: > 6.8 ms */
	/* master operation start; in fast-trigger mode the sensor now waits
	 * for XTRIG1 falling edges. First 8 frames are not guaranteed (DS 16.1). */
	return imx568_write_reg(priv->s_data, IMX568_XMSTA, 0x00);
}

static int imx568_stop_streaming(struct tegracam_device *tc_dev)
{
	struct imx568 *priv = tegracam_get_privdata(tc_dev);

#ifdef IMX568_GMSL
	mutex_lock(&serdes_lock__);
	max9296_stop_streaming(priv->dser_dev, tc_dev->dev);
	mutex_unlock(&serdes_lock__);
#endif
	imx568_write_reg(priv->s_data, IMX568_XMSTA, 0x01);
	imx568_write_reg(priv->s_data, IMX568_STANDBY, 0x01);
	usleep_range(200, 300);			/* >= 150 us standby sequence */
	return 0;
}

static struct camera_common_pdata *imx568_parse_dt(struct tegracam_device *tc_dev)
{
	if (!tc_dev->dev->of_node)
		return NULL;
	return devm_kzalloc(tc_dev->dev, sizeof(struct camera_common_pdata), GFP_KERNEL);
}

static struct camera_common_sensor_ops imx568_common_ops = {
	.numfrmfmts = ARRAY_SIZE(imx568_frmfmt),
	.frmfmt_table = imx568_frmfmt,
	.power_on = imx568_power_on,
	.power_off = imx568_power_off,
	.write_reg = imx568_write_reg,
	.read_reg = imx568_read_reg,
	.parse_dt = imx568_parse_dt,
	.power_get = imx568_power_get,
	.power_put = imx568_power_put,
	.set_mode = imx568_set_mode,
	.start_streaming = imx568_start_streaming,
	.stop_streaming = imx568_stop_streaming,
};

/* ------------------------------------------------------------ board / DT */
static int imx568_board_setup_common(struct imx568 *priv)
{
	struct device_node *node = priv->i2c_client->dev.of_node;
	const char *s;

	priv->sync_mode = IMX568_SYNC_FAST_TRIGGER;
	if (!of_property_read_string(node, "imx568,sync-mode", &s) && !strcmp(s, "master"))
		priv->sync_mode = IMX568_SYNC_MASTER;
	return 0;
}

#ifndef IMX568_GMSL
static int imx568_board_setup(struct imx568 *priv)
{
	struct device *dev = &priv->i2c_client->dev;

	imx568_board_setup_common(priv);
	priv->vdd = devm_regulator_get(dev, "vdd-stereo");
	if (IS_ERR(priv->vdd))
		return dev_err_probe(dev, PTR_ERR(priv->vdd), "vdd-stereo-supply\n");
	/* STATUS is shared by the two sensors of a board: request non-exclusive */
	priv->status_gpio = devm_gpiod_get_optional(dev, "status",
						    GPIOD_IN | GPIOD_FLAGS_BIT_NONEXCLUSIVE);
	if (IS_ERR(priv->status_gpio))
		return dev_err_probe(dev, PTR_ERR(priv->status_gpio), "status-gpios\n");
	priv->ready_timeout_ms = 200;
	of_property_read_u32(dev->of_node, "imx568,ready-timeout-ms", &priv->ready_timeout_ms);
	return 0;
}
#else
static int imx568_parse_gmsl(struct imx568 *priv, struct device_node *node)
{
	struct device *dev = &priv->i2c_client->dev;
	struct device_node *gmsl;
	const char *s;
	u32 v;
	int i, err = 0;

	gmsl = of_get_child_by_name(node, "gmsl-link");
	if (!gmsl) {
		dev_err(dev, "missing gmsl-link node\n");
		return -EINVAL;
	}
#define RD_STR(prop) do { if (of_property_read_string(gmsl, prop, &s)) { \
		dev_err(dev, "gmsl-link: missing %s\n", prop); err = -EINVAL; goto out; } } while (0)
#define RD_U32(prop) do { if (of_property_read_u32(gmsl, prop, &v)) { \
		dev_err(dev, "gmsl-link: missing %s\n", prop); err = -EINVAL; goto out; } } while (0)

	RD_STR("dst-csi-port");
	priv->g_ctx.dst_csi_port = !strcmp(s, "a") ? GMSL_CSI_PORT_A : GMSL_CSI_PORT_B;
	RD_STR("src-csi-port");
	priv->g_ctx.src_csi_port = !strcmp(s, "a") ? GMSL_CSI_PORT_A : GMSL_CSI_PORT_B;
	RD_STR("csi-mode");
	if (!strcmp(s, "1x4"))
		priv->g_ctx.csi_mode = GMSL_CSI_1X4_MODE;
	else if (!strcmp(s, "2x4"))
		priv->g_ctx.csi_mode = GMSL_CSI_2X4_MODE;
	else if (!strcmp(s, "4x2"))
		priv->g_ctx.csi_mode = GMSL_CSI_4X2_MODE;
	else if (!strcmp(s, "2x2"))
		priv->g_ctx.csi_mode = GMSL_CSI_2X2_MODE;
	else {
		dev_err(dev, "invalid csi-mode %s\n", s);
		err = -EINVAL;
		goto out;
	}
	RD_STR("serdes-csi-link");
	priv->g_ctx.serdes_csi_link = !strcmp(s, "a") ? GMSL_SERDES_CSI_LINK_A :
							 GMSL_SERDES_CSI_LINK_B;
	RD_U32("st-vc");
	priv->g_ctx.st_vc = v;
	RD_U32("vc-id");
	priv->g_ctx.dst_vc = v;
	RD_U32("num-lanes");
	priv->g_ctx.num_csi_lanes = v;

	/* the L4T MAX9295/MAX9296 drivers only map RAW12 (and embedded) pipes */
	i = of_property_count_strings(gmsl, "streams");
	if (i <= 0 || i > GMSL_DEV_MAX_NUM_DATA_STREAMS) {
		dev_err(dev, "gmsl-link: bad streams\n");
		err = -EINVAL;
		goto out;
	}
	priv->g_ctx.num_streams = i;
	for (i = 0; i < priv->g_ctx.num_streams; i++) {
		of_property_read_string_index(gmsl, "streams", i, &s);
		if (!strcmp(s, "raw12"))
			priv->g_ctx.streams[i].st_data_type = GMSL_CSI_DT_RAW_12;
		else if (!strcmp(s, "embed"))
			priv->g_ctx.streams[i].st_data_type = GMSL_CSI_DT_EMBED;
		else {
			dev_err(dev, "unsupported stream type %s\n", s);
			err = -EINVAL;
			goto out;
		}
	}
#undef RD_STR
#undef RD_U32
out:
	of_node_put(gmsl);
	return err;
}

static int imx568_board_setup(struct imx568 *priv)
{
	struct device *dev = &priv->i2c_client->dev;
	struct device_node *node = dev->of_node, *np;
	struct i2c_client *c;
	int err, n;

	imx568_board_setup_common(priv);
	err = of_property_read_u32(node, "reg", &priv->g_ctx.sdev_reg);
	err = err ?: of_property_read_u32(node, "def-addr", &priv->g_ctx.sdev_def);
	if (err) {
		dev_err(dev, "reg/def-addr missing\n");
		return -EINVAL;
	}

	np = of_parse_phandle(node, "nvidia,gmsl-ser-device", 0);
	if (!np || of_property_read_u32(np, "reg", &priv->g_ctx.ser_reg)) {
		of_node_put(np);
		dev_err(dev, "nvidia,gmsl-ser-device missing\n");
		return -EINVAL;
	}
	c = of_find_i2c_device_by_node(np);
	of_node_put(np);
	if (!c || !c->dev.driver)
		return -EPROBE_DEFER;
	priv->ser_dev = &c->dev;

	np = of_parse_phandle(node, "nvidia,gmsl-dser-device", 0);
	if (!np) {
		dev_err(dev, "nvidia,gmsl-dser-device missing\n");
		return -EINVAL;
	}
	c = of_find_i2c_device_by_node(np);
	of_node_put(np);
	if (!c || !c->dev.driver)
		return -EPROBE_DEFER;
	priv->dser_dev = &c->dev;

	priv->ser_map = dev_get_regmap(priv->ser_dev, NULL);
	priv->dser_map = dev_get_regmap(priv->dser_dev, NULL);
	if (!priv->ser_map || !priv->dser_map) {
		dev_err(dev, "serdes regmap not found\n");
		return -ENODEV;
	}

	err = imx568_parse_gmsl(priv, node);
	if (err)
		return err;
	priv->g_ctx.s_dev = dev;

	if (of_property_read_u32_array(node, "imx568,mfp-en", priv->mfp_en, EN_NUM) ||
	    of_property_read_u32(node, "imx568,mfp-xclr", &priv->mfp_xclr) ||
	    of_property_read_u32(node, "imx568,mfp-xtrig", &priv->mfp_xtrig)) {
		dev_err(dev, "imx568,mfp-en/-xclr/-xtrig missing\n");
		return -EINVAL;
	}
	priv->mfp_tout0 = SER_NUM_MFP;
	of_property_read_u32(node, "imx568,mfp-tout0", &priv->mfp_tout0);
	priv->gpio_id_trig = 0;
	of_property_read_u32(node, "imx568,gmsl-gpio-id-trig", &priv->gpio_id_trig);
	priv->gpio_id_tout0 = 1;
	of_property_read_u32(node, "imx568,gmsl-gpio-id-tout0", &priv->gpio_id_tout0);
	of_property_read_u32(node, "imx568,dser-phy-rate-mbps", &priv->dser_phy_mbps);
	if (priv->dser_phy_mbps && (priv->dser_phy_mbps < 100 || priv->dser_phy_mbps > 2500)) {
		dev_err(dev, "dser-phy-rate-mbps out of range\n");
		return -EINVAL;
	}

	n = of_property_count_u16_elems(node, "imx568,dser-init-regs");
	if (n > 0) {
		if (n % 2) {
			dev_err(dev, "imx568,dser-init-regs must be <addr val> pairs\n");
			return -EINVAL;
		}
		priv->dser_regs = devm_kcalloc(dev, n, sizeof(u16), GFP_KERNEL);
		if (!priv->dser_regs)
			return -ENOMEM;
		of_property_read_u16_array(node, "imx568,dser-init-regs", priv->dser_regs, n);
		priv->n_dser_regs = n / 2;
	}
	return 0;
}

static int imx568_gmsl_serdes_setup(struct imx568 *priv)
{
	struct device *dev = &priv->i2c_client->dev;
	int i, err, des_err;

	mutex_lock(&serdes_lock__);
	max9296_power_on(priv->dser_dev);

	err = max9296_setup_link(priv->dser_dev, dev);
	if (err) {
		dev_err(dev, "deserializer link setup failed\n");
		goto out;
	}
	err = max9295_setup_control(priv->ser_dev);
	if (err)
		dev_err(dev, "serializer setup failed\n");	/* continue: fix up deser */
	des_err = max9296_setup_control(priv->dser_dev, dev);
	if (des_err) {
		dev_err(dev, "deserializer setup failed\n");
		err = des_err;
	}
	/* trigger fan-out on the deserializer (GPIO TX on its MFP), board specific */
	for (i = 0; !err && i < priv->n_dser_regs; i++)
		err = regmap_write(priv->dser_map, priv->dser_regs[2 * i],
				   priv->dser_regs[2 * i + 1] & 0xFF);
out:
	mutex_unlock(&serdes_lock__);
	return err;
}

static void imx568_gmsl_serdes_reset(struct imx568 *priv)
{
	mutex_lock(&serdes_lock__);
	max9295_reset_control(priv->ser_dev);
	max9296_reset_control(priv->dser_dev, &priv->i2c_client->dev);
	max9296_power_off(priv->dser_dev);
	mutex_unlock(&serdes_lock__);
}
#endif

static int imx568_detect(struct imx568 *priv)
{
	struct camera_common_data *s_data = priv->s_data;
	struct device *dev = &priv->i2c_client->dev;
	u8 stby = 0, hl = 0, hh = 0;
	int err;

	err = imx568_power_on(s_data);
	if (err)
		return err;
	/* no chip-ID register in the Lite DS: check documented reset values */
	err = imx568_read_reg(s_data, IMX568_STANDBY, &stby);
	err = err ?: imx568_read_reg(s_data, IMX568_HMAX_L, &hl);
	err = err ?: imx568_read_reg(s_data, IMX568_HMAX_L + 1, &hh);
	imx568_power_off(s_data);
	if (err) {
		dev_err(dev, "sensor not responding at 0x%02x\n", priv->i2c_client->addr);
		return -ENODEV;
	}
	if (!(stby & 1) || ((hh << 8) | hl) != 0x0167)
		dev_warn(dev, "unexpected reset values STANDBY=0x%02x HMAX=0x%04x\n",
			 stby, (hh << 8) | hl);
	return 0;
}

/* ------------------------------------------------------------ sysfs (for the sync tool) */
static struct imx568 *dev_to_priv(struct device *dev)
{
	struct camera_common_data *s_data = to_camera_common_data(dev);

	return s_data ? s_data->priv : NULL;
}

static ssize_t line_time_ns_show(struct device *dev, struct device_attribute *a, char *buf)
{
	struct imx568 *priv = dev_to_priv(dev);

	return sprintf(buf, "%u\n", priv && priv->mode ? priv->line_ns : 0);
}
static DEVICE_ATTR_RO(line_time_ns);

static ssize_t trigger_offset_ns_show(struct device *dev, struct device_attribute *a, char *buf)
{
	struct imx568 *priv = dev_to_priv(dev);

	if (!priv || !priv->mode)
		return sprintf(buf, "0\n");
	/* exposure = XTRIG low width + this value (DS 16.6.3) */
	return sprintf(buf, "%u\n", priv->mode->gmrwt * priv->line_ns + IMX568_TOFFSET_FAST_NS);
}
static DEVICE_ATTR_RO(trigger_offset_ns);

static ssize_t min_trigger_period_ns_show(struct device *dev, struct device_attribute *a, char *buf)
{
	struct imx568 *priv = dev_to_priv(dev);

	if (!priv || !priv->mode)
		return sprintf(buf, "0\n");
	/* next-trigger prohibited period tTGPD = VMAX lines after trigger rise */
	return sprintf(buf, "%llu\n", (u64)priv->mode->vmax * priv->line_ns);
}
static DEVICE_ATTR_RO(min_trigger_period_ns);

static struct attribute *imx568_attrs[] = {
	&dev_attr_line_time_ns.attr,
	&dev_attr_trigger_offset_ns.attr,
	&dev_attr_min_trigger_period_ns.attr,
	NULL,
};
static const struct attribute_group imx568_attr_group = { .attrs = imx568_attrs };

/* ------------------------------------------------------------ probe/remove */
static int imx568_open(struct v4l2_subdev *sd, struct v4l2_subdev_fh *fh)
{
	return 0;
}

static const struct v4l2_subdev_internal_ops imx568_subdev_internal_ops = {
	.open = imx568_open,
};

static const struct of_device_id imx568_of_match[] = {
	{ .compatible = "sony,imx568" },
	{ },
};
MODULE_DEVICE_TABLE(of, imx568_of_match);

#if LINUX_VERSION_CODE >= KERNEL_VERSION(6, 3, 0)
static int imx568_probe(struct i2c_client *client)
#else
static int imx568_probe(struct i2c_client *client, const struct i2c_device_id *id)
#endif
{
	struct device *dev = &client->dev;
	struct tegracam_device *tc_dev;
	struct imx568 *priv;
	int err;

	if (!IS_ENABLED(CONFIG_OF) || !dev->of_node)
		return -EINVAL;

	priv = devm_kzalloc(dev, sizeof(*priv), GFP_KERNEL);
	tc_dev = devm_kzalloc(dev, sizeof(*tc_dev), GFP_KERNEL);
	if (!priv || !tc_dev)
		return -ENOMEM;

	priv->i2c_client = tc_dev->client = client;
	tc_dev->dev = dev;
	strscpy(tc_dev->name, "imx568", sizeof(tc_dev->name));
	tc_dev->dev_regmap_config = &sensor_regmap_config;
	tc_dev->sensor_ops = &imx568_common_ops;
	tc_dev->v4l2sd_internal_ops = &imx568_subdev_internal_ops;
	tc_dev->tcctrl_ops = &imx568_ctrl_ops;

	err = tegracam_device_register(tc_dev);
	if (err) {
		dev_err(dev, "tegracam registration failed\n");
		return err;
	}
	priv->tc_dev = tc_dev;
	priv->s_data = tc_dev->s_data;
	priv->subdev = &tc_dev->s_data->subdev;
	tegracam_set_privdata(tc_dev, priv);

	err = imx568_board_setup(priv);
	if (err)
		goto unreg;

#ifdef IMX568_GMSL
	err = max9295_sdev_pair(priv->ser_dev, &priv->g_ctx);
	if (err) {
		dev_err(dev, "serializer pairing failed\n");
		goto unreg;
	}
	err = max9296_sdev_register(priv->dser_dev, &priv->g_ctx);
	if (err) {
		dev_err(dev, "deserializer registration failed\n");
		goto unpair;
	}
	/* serdes setup lives in probe for the same reason as nv_imx390 (BUG 200477330) */
	err = imx568_gmsl_serdes_setup(priv);
	if (err)
		goto unregister_sdev;
#endif

	err = imx568_detect(priv);
	if (err)
		goto serdes_reset;

	err = tegracam_v4l2subdev_register(tc_dev, true);
	if (err) {
		dev_err(dev, "v4l2 subdev registration failed\n");
		goto serdes_reset;
	}
	if (sysfs_create_group(&dev->kobj, &imx568_attr_group))
		dev_warn(dev, "sysfs attributes not created\n");

	dev_info(dev, "IMX568 @0x%02x ready (%s, %s)\n", client->addr,
#ifdef IMX568_GMSL
		 "GMSL",
#else
		 "stereo board / FPC",
#endif
		 priv->sync_mode == IMX568_SYNC_FAST_TRIGGER ? "fast-trigger" : "free-run");
	return 0;

serdes_reset:
#ifdef IMX568_GMSL
	imx568_gmsl_serdes_reset(priv);
unregister_sdev:
	max9296_sdev_unregister(priv->dser_dev, dev);
unpair:
	max9295_sdev_unpair(priv->ser_dev, dev);
#endif
unreg:
	tegracam_device_unregister(tc_dev);
	return err;
}

#if LINUX_VERSION_CODE >= KERNEL_VERSION(6, 1, 0)
static void imx568_remove(struct i2c_client *client)
#else
static int imx568_remove(struct i2c_client *client)
#endif
{
	struct camera_common_data *s_data = to_camera_common_data(&client->dev);
	struct imx568 *priv = s_data->priv;

	sysfs_remove_group(&client->dev.kobj, &imx568_attr_group);
	if (priv->rail_on)
		imx568_power_off(s_data);
#ifdef IMX568_GMSL
	imx568_gmsl_serdes_reset(priv);
	max9296_sdev_unregister(priv->dser_dev, &client->dev);
	max9295_sdev_unpair(priv->ser_dev, &client->dev);
#endif
	tegracam_v4l2subdev_unregister(priv->tc_dev);
	tegracam_device_unregister(priv->tc_dev);
#if LINUX_VERSION_CODE < KERNEL_VERSION(6, 1, 0)
	return 0;
#endif
}

static const struct i2c_device_id imx568_id[] = {
	{ "imx568", 0 },
	{ }
};
MODULE_DEVICE_TABLE(i2c, imx568_id);

static struct i2c_driver imx568_i2c_driver = {
	.driver = {
		.name = "imx568",
		.of_match_table = of_match_ptr(imx568_of_match),
	},
	.probe = imx568_probe,
	.remove = imx568_remove,
	.id_table = imx568_id,
};

static int __init imx568_init(void)
{
#ifdef IMX568_GMSL
	mutex_init(&serdes_lock__);
#endif
	return i2c_add_driver(&imx568_i2c_driver);
}

static void __exit imx568_exit(void)
{
	i2c_del_driver(&imx568_i2c_driver);
#ifdef IMX568_GMSL
	mutex_destroy(&serdes_lock__);
#endif
}

module_init(imx568_init);
module_exit(imx568_exit);

MODULE_DESCRIPTION("Sony IMX568 (stereo board over FPC, or GMSL2) for NVIDIA Jetson");
MODULE_LICENSE("GPL v2");
