/* compile-test stub: subset of L4T R35 camera_common.h / tegracam_core.h */
#ifndef __TEGRACAM_STUB_H__
#define __TEGRACAM_STUB_H__
#include <linux/i2c.h>
#include <linux/regmap.h>
#include <linux/clk.h>
#include <media/v4l2-subdev.h>
#include <media/v4l2-ctrls.h>
#define TEGRA_CAMERA_CID_BASE (V4L2_CTRL_CLASS_CAMERA | 0x2000)
#define TEGRA_CAMERA_CID_FRAME_RATE (TEGRA_CAMERA_CID_BASE+0)
#define TEGRA_CAMERA_CID_GAIN (TEGRA_CAMERA_CID_BASE+1)
#define TEGRA_CAMERA_CID_EXPOSURE (TEGRA_CAMERA_CID_BASE+2)
#define TEGRA_CAMERA_CID_SENSOR_MODE_ID (TEGRA_CAMERA_CID_BASE+3)
enum switch_state { SWITCH_OFF, SWITCH_ON };
struct sensor_control_properties { __u32 gain_factor, framerate_factor, exposure_factor; };
struct sensor_mode_properties { struct sensor_control_properties control_properties; };
struct sensor_properties { struct sensor_mode_properties *sensor_modes; u32 num_modes; };
struct camera_common_power_rail { struct clk *mclk; bool state; };
struct camera_common_pdata { const char *mclk_name, *parentclk_name;
	int (*power_on)(struct camera_common_power_rail *); int (*power_off)(struct camera_common_power_rail *); };
struct camera_common_frmfmt { struct v4l2_frmsize_discrete size; const int *framerates;
	int num_framerates; bool hdr_en; int mode; };
struct tegracam_device;
struct camera_common_data;
struct camera_common_sensor_ops {
	u32 numfrmfmts; const struct camera_common_frmfmt *frmfmt_table;
	int (*power_on)(struct camera_common_data *); int (*power_off)(struct camera_common_data *);
	int (*write_reg)(struct camera_common_data *, u16, u8);
	int (*read_reg)(struct camera_common_data *, u16, u8 *);
	struct camera_common_pdata *(*parse_dt)(struct tegracam_device *);
	int (*power_get)(struct tegracam_device *); int (*power_put)(struct tegracam_device *);
	int (*set_mode)(struct tegracam_device *); int (*start_streaming)(struct tegracam_device *);
	int (*stop_streaming)(struct tegracam_device *);
};
struct camera_common_data {
	struct camera_common_sensor_ops *ops; struct device *dev;
	struct camera_common_power_rail *power; struct v4l2_subdev subdev;
	struct sensor_properties sensor_props; struct regmap *regmap;
	struct camera_common_pdata *pdata; int mode_prop_idx; void *priv;
};
struct tegracam_ctrl_ops {
	u32 numctrls; const u32 *ctrl_cid_list; bool is_blob_supported;
	int (*set_gain)(struct tegracam_device *, s64); int (*set_exposure)(struct tegracam_device *, s64);
	int (*set_exposure_short)(struct tegracam_device *, s64);
	int (*set_frame_rate)(struct tegracam_device *, s64); int (*set_group_hold)(struct tegracam_device *, bool);
};
struct tegracam_device {
	struct camera_common_data *s_data; char name[32]; struct i2c_client *client; struct device *dev;
	const struct regmap_config *dev_regmap_config; struct camera_common_sensor_ops *sensor_ops;
	const struct v4l2_subdev_internal_ops *v4l2sd_internal_ops;
	const struct tegracam_ctrl_ops *tcctrl_ops; void *priv;
};
struct camera_common_data *to_camera_common_data(const struct device *dev);
void tegracam_set_privdata(struct tegracam_device *tc_dev, void *priv);
void *tegracam_get_privdata(struct tegracam_device *tc_dev);
int tegracam_v4l2subdev_register(struct tegracam_device *tc_dev, bool is_sensor);
void tegracam_v4l2subdev_unregister(struct tegracam_device *tc_dev);
int tegracam_device_register(struct tegracam_device *tc_dev);
void tegracam_device_unregister(struct tegracam_device *tc_dev);
#endif
