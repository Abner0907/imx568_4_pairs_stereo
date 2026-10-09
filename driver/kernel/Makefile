# Out-of-tree build of nv_imx568.ko for Jetson AGX Xavier (L4T R35.x, kernel 5.10).
#
# On the Jetson (kernel headers package installed):
#     make
# Cross-compiling against the L4T public kernel sources:
#     make KERNEL_SRC=<Linux_for_Tegra>/source/public/kernel/kernel-5.10 \
#          NVIDIA_INC=<Linux_for_Tegra>/source/public/kernel/nvidia/include \
#          ARCH=arm64 CROSS_COMPILE=aarch64-buildroot-linux-gnu-
#
# Alternatively copy nv_imx568.c + imx568_mode_tbls.h into
# kernel/nvidia/drivers/media/i2c/ and add "obj-m += nv_imx568.o" there.
#
# Once the NDA register tables are filled in, build with  EXTRA_CFLAGS=-DIMX568_HAVE_FULL_REGMAP

KERNEL_SRC ?= /lib/modules/$(shell uname -r)/build
NVIDIA_INC ?= $(KERNEL_SRC)/../nvidia/include

# GMSL=1 builds variant B (MAX9295A/MAX9296A camera heads) instead of the
# default stereo-board/FPC variant A.
GMSL ?= 0

obj-m := nv_imx568.o
ccflags-y += -I$(NVIDIA_INC) $(EXTRA_CFLAGS)
ifeq ($(GMSL),1)
ccflags-y += -DIMX568_GMSL
endif

all:
	$(MAKE) -C $(KERNEL_SRC) M=$(CURDIR) modules

clean:
	$(MAKE) -C $(KERNEL_SRC) M=$(CURDIR) clean

install:
	$(MAKE) -C $(KERNEL_SRC) M=$(CURDIR) modules_install
	depmod -a
