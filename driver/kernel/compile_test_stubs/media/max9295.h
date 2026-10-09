#include <media/gmsl-link.h>
int max9295_setup_control(struct device *dev);
int max9295_reset_control(struct device *dev);
int max9295_sdev_pair(struct device *dev, struct gmsl_link_ctx *g_ctx);
int max9295_sdev_unpair(struct device *dev, struct device *s_dev);
int max9295_setup_streaming(struct device *dev);
