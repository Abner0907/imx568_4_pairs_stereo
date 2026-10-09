#include <media/gmsl-link.h>
int max9296_setup_link(struct device *dev, struct device *s_dev);
int max9296_setup_control(struct device *dev, struct device *s_dev);
int max9296_reset_control(struct device *dev, struct device *s_dev);
int max9296_sdev_register(struct device *dev, struct gmsl_link_ctx *g_ctx);
int max9296_sdev_unregister(struct device *dev, struct device *s_dev);
int max9296_setup_streaming(struct device *dev, struct device *s_dev);
int max9296_start_streaming(struct device *dev, struct device *s_dev);
int max9296_stop_streaming(struct device *dev, struct device *s_dev);
int max9296_power_on(struct device *dev);
void max9296_power_off(struct device *dev);
