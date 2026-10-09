/* stub copied from L4T R35 nvidia/include/media/gmsl-link.h (subset) */
#ifndef __GMSL_LINK_H__
#define __GMSL_LINK_H__
#define GMSL_CSI_1X4_MODE 0x1
#define GMSL_CSI_2X4_MODE 0x2
#define GMSL_CSI_2X2_MODE 0x3
#define GMSL_CSI_4X2_MODE 0x4
#define GMSL_CSI_PORT_A 0x0
#define GMSL_CSI_PORT_B 0x1
#define GMSL_SERDES_CSI_LINK_A 0x1
#define GMSL_SERDES_CSI_LINK_B 0x2
#define GMSL_CSI_DT_RAW_12 0x2C
#define GMSL_CSI_DT_UED_U1 0x30
#define GMSL_CSI_DT_EMBED 0x12
#define GMSL_DEV_MAX_NUM_DATA_STREAMS 4
struct gmsl_stream { __u32 st_id_sel; __u32 st_data_type; __u32 des_pipe; };
struct gmsl_link_ctx {
	__u32 st_vc, dst_vc, src_csi_port, dst_csi_port, serdes_csi_link, num_streams,
	      num_csi_lanes, csi_mode, ser_reg, sdev_reg, sdev_def;
	bool serdev_found;
	struct gmsl_stream streams[GMSL_DEV_MAX_NUM_DATA_STREAMS];
	struct device *s_dev;
};
#endif
