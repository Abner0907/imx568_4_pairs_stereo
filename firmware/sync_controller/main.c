/*
 * IMX568 x8 stereo-VIO sync controller (RP2040, Pico SDK >= 1.5)
 *
 *  TRIG0..3  -> (variant A) adapter level shifter -> FPC k -> stereo board k
 *               FPGA -> XTRIG of both IMX568;  (variant B) MAX9296A #k MFP ->
 *               GMSL GPIO -> both MAX9295A -> XTRIG1.  Active-low pulse; IMX568 fast-trigger
 *               mode: exposure = low width + offset (offset = GMRWT*1H + 2.53 us,
 *               read it from /sys/.../trigger_offset_ns and send "OFFSET").
 *  SYNC_OUT  -> Xavier GPIO. Rising edge at the common MID-EXPOSURE instant of
 *               all pairs; capture it with the GPIO uAPI for a CLOCK_MONOTONIC
 *               image timestamp (see software/sync_capture).
 *
 * All four pairs share the same mid-exposure instant even with different
 * exposures (pair k falls at C - E_k/2), which is what a multi-camera VIO
 * estimator wants. Every frame is also reported over USB-CDC:
 *     F <seq> <t_mid_us> <E0> <E1> <E2> <E3>
 *
 * USB-CDC commands (newline terminated):
 *     FPS <hz>            frame rate (float)
 *     EXP <k|*> <us>      exposure of pair k (0..3) or all
 *     OFFSET <ns>         sensor exposure offset (trigger_offset_ns)
 *     MINPER <ns>         sensor trigger prohibited period (min_trigger_period_ns)
 *     MASK <hex>          enabled pairs, bit k = pair k (default f)
 *     START | STOP | STATUS | PING
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "hardware/clocks.h"
#include "hardware/gpio.h"
#include "hardware/pio.h"
#include "hardware/sync.h"
#include "pico/stdlib.h"

#include "trigger.pio.h"

#define PIN_TRIG0	2	/* TRIG0..TRIG3 on GP2..GP5 */
#define PIN_SYNC_OUT	6
#define PIN_LED		25
#define NUM_PAIRS	4
#define SYNC_PULSE_US	20
#define MARGIN_US	50	/* guard added to the prohibited period */

static PIO const trig_pio = pio0;	/* SM0..3 = TRIG0..3 */
static PIO const sync_pio = pio1;	/* SM0 = SYNC_OUT */

static struct {
	float fps;
	uint32_t exp_us[NUM_PAIRS];
	uint32_t offset_ns;
	uint32_t minper_ns;
	uint32_t mask;
	bool running;
} cfg = {
	.fps = 30.0f,
	.exp_us = { 5000, 5000, 5000, 5000 },
	.offset_ns = 0,			/* must be set from the driver's sysfs */
	.minper_ns = 10000000,		/* conservative until told otherwise */
	.mask = 0xF,
};

/* per-frame values computed once per configuration change */
static struct {
	uint32_t delay_cyc[NUM_PAIRS], width_cyc[NUM_PAIRS];
	uint32_t center_cyc, center_us;
	uint32_t period_us;
} plan;

static volatile uint32_t seq;
static struct repeating_timer timer;

/* tiny lock-free ring buffer: timer IRQ -> main loop (USB printing) */
#define RB_N 64
static struct { uint32_t seq; uint64_t t_mid; } rb[RB_N];
static volatile uint32_t rb_w, rb_r;

static uint32_t us_to_cyc(uint32_t us)
{
	return (uint32_t)((uint64_t)us * clock_get_hz(clk_sys) / 1000000u);
}

/* returns NULL on success or a reason string */
static const char *compute_plan(void)
{
	uint32_t half_max = 0, wmax_us = 0;
	uint32_t off_us = (cfg.offset_ns + 999) / 1000;

	if (cfg.fps < 0.5f || cfg.fps > 250.0f)
		return "fps out of range";
	for (int k = 0; k < NUM_PAIRS; k++) {
		if (!(cfg.mask & (1u << k)))
			continue;
		if (cfg.exp_us[k] <= off_us + 1)
			return "exposure shorter than sensor offset";
		if (cfg.exp_us[k] / 2 > half_max)
			half_max = cfg.exp_us[k] / 2;
		if (cfg.exp_us[k] - off_us > wmax_us)
			wmax_us = cfg.exp_us[k] - off_us;
	}
	plan.period_us = (uint32_t)(1e6f / cfg.fps + 0.5f);
	/* DS 16.6.3: next trigger edge must wait tTGPD (= VMAX lines) after rise */
	if (plan.period_us < wmax_us + cfg.minper_ns / 1000 + MARGIN_US)
		return "period < exposure + sensor readout (lower FPS or exposure)";

	plan.center_us = half_max + 10;			/* mid-exposure, from start */
	plan.center_cyc = us_to_cyc(plan.center_us);
	for (int k = 0; k < NUM_PAIRS; k++) {
		uint32_t e = cfg.exp_us[k], w = e - off_us;
		/* true exposure = [fall, fall + E]; centre it on C */
		plan.delay_cyc[k] = plan.center_cyc - us_to_cyc(e) / 2;
		plan.width_cyc[k] = us_to_cyc(w) - 2;	/* PIO loop overhead */
	}
	return NULL;
}

static bool on_frame(struct repeating_timer *t)
{
	(void)t;
	uint32_t mask = cfg.mask & 0xF;
	uint64_t t0;

	/* stage values; SMs block at 'wait irq' until the force below */
	for (int k = 0; k < NUM_PAIRS; k++) {
		if (mask & (1u << k)) {
			pio_sm_put(trig_pio, k, plan.delay_cyc[k]);
			pio_sm_put(trig_pio, k, plan.width_cyc[k]);
		}
	}
	pio_sm_put(sync_pio, 0, plan.center_cyc);
	pio_sm_put(sync_pio, 0, us_to_cyc(SYNC_PULSE_US) - 2);
	busy_wait_us_32(2);

	uint32_t irq = save_and_disable_interrupts();
	t0 = time_us_64();
	trig_pio->irq_force = mask;		/* all trigger SMs start together */
	sync_pio->irq_force = 1u;
	restore_interrupts(irq);

	uint32_t w = rb_w;
	if (((w + 1) % RB_N) != rb_r) {
		rb[w].seq = seq;
		rb[w].t_mid = t0 + plan.center_us;
		rb_w = (w + 1) % RB_N;
	}
	seq++;
	gpio_put(PIN_LED, seq & 8);
	return true;
}

static void stop(void)
{
	if (cfg.running)
		cancel_repeating_timer(&timer);
	cfg.running = false;
	gpio_put(PIN_LED, 0);
}

static const char *start(void)
{
	const char *err = compute_plan();

	if (err)
		return err;
	stop();
	/* drop anything left in the FIFOs from a previous run */
	for (int k = 0; k < NUM_PAIRS; k++)
		pio_sm_clear_fifos(trig_pio, k);
	pio_sm_clear_fifos(sync_pio, 0);
	cfg.running = add_repeating_timer_us(-(int64_t)plan.period_us, on_frame, NULL, &timer);
	return cfg.running ? NULL : "no timer slot";
}

static void handle(char *line)
{
	char *cmd = strtok(line, " \t\r\n");
	char *a1 = strtok(NULL, " \t\r\n");
	char *a2 = strtok(NULL, " \t\r\n");
	const char *err = NULL;
	bool was_running = cfg.running;

	if (!cmd)
		return;
	if (!strcmp(cmd, "FPS") && a1) {
		cfg.fps = strtof(a1, NULL);
	} else if (!strcmp(cmd, "EXP") && a1 && a2) {
		uint32_t us = strtoul(a2, NULL, 0);
		for (int k = 0; k < NUM_PAIRS; k++)
			if (a1[0] == '*' || atoi(a1) == k)
				cfg.exp_us[k] = us;
	} else if (!strcmp(cmd, "OFFSET") && a1) {
		cfg.offset_ns = strtoul(a1, NULL, 0);
	} else if (!strcmp(cmd, "MINPER") && a1) {
		cfg.minper_ns = strtoul(a1, NULL, 0);
	} else if (!strcmp(cmd, "MASK") && a1) {
		cfg.mask = strtoul(a1, NULL, 16) & 0xF;
	} else if (!strcmp(cmd, "START")) {
		err = start();
		was_running = false;
	} else if (!strcmp(cmd, "STOP")) {
		stop();
		was_running = false;
	} else if (!strcmp(cmd, "PING")) {
		printf("PONG %llu\n", (unsigned long long)time_us_64());
		return;
	} else if (strcmp(cmd, "STATUS")) {
		printf("ERR unknown command\n");
		return;
	}
	/* parameter change while running: restart on the new plan */
	if (!err && was_running)
		err = start();
	else if (!err && !cfg.running)
		err = compute_plan();
	if (err)
		printf("ERR %s\n", err);
	else
		printf("OK run=%d fps=%.3f period_us=%lu exp=%lu,%lu,%lu,%lu offset_ns=%lu minper_ns=%lu mask=%lx\n",
		       cfg.running, cfg.fps, (unsigned long)plan.period_us,
		       (unsigned long)cfg.exp_us[0], (unsigned long)cfg.exp_us[1],
		       (unsigned long)cfg.exp_us[2], (unsigned long)cfg.exp_us[3],
		       (unsigned long)cfg.offset_ns, (unsigned long)cfg.minper_ns,
		       (unsigned long)cfg.mask);
}

int main(void)
{
	char line[96];
	int n = 0;

	stdio_init_all();
	gpio_init(PIN_LED);
	gpio_set_dir(PIN_LED, GPIO_OUT);

	uint off0 = pio_add_program(trig_pio, &trigger_program);
	uint off1 = pio_add_program(sync_pio, &trigger_program);
	for (int k = 0; k < NUM_PAIRS; k++)
		trigger_program_init(trig_pio, k, off0, PIN_TRIG0 + k, false);
	trigger_program_init(sync_pio, 0, off1, PIN_SYNC_OUT, true);

	for (;;) {
		int c = getchar_timeout_us(1000);

		if (c >= 0) {
			if (c == '\n' || c == '\r') {
				line[n] = 0;
				if (n)
					handle(line);
				n = 0;
			} else if (n < (int)sizeof(line) - 1) {
				line[n++] = (char)c;
			}
		}
		while (rb_r != rb_w) {
			uint32_t r = rb_r;
			printf("F %lu %llu %lu %lu %lu %lu\n", (unsigned long)rb[r].seq,
			       (unsigned long long)rb[r].t_mid,
			       (unsigned long)cfg.exp_us[0], (unsigned long)cfg.exp_us[1],
			       (unsigned long)cfg.exp_us[2], (unsigned long)cfg.exp_us[3]);
			rb_r = (r + 1) % RB_N;
		}
	}
}
