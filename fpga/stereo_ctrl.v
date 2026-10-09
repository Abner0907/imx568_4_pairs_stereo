// stereo_ctrl.v - board control for the IMX568 stereo pair board (CrossLink-NX)
//
// Instantiate next to Lattice's "MIPI CSI-2 Virtual Channel Aggregation"
// reference design (2 RX -> 1 TX, RX0 = left -> VC0, RX1 = right -> VC1).
//
//  * power sequencing for BOTH sensors (shared rails), IMX568 DS 17.1 / 17.3:
//      up  : EN_1V1 -> EN_1V8 -> EN_2V9 -> EN_3V3 (T_STEP each, slew by TPS22918 CT)
//            -> XCLR high (after T_LOW) -> INCK OE (after >= 1 us) -> READY
//      down: XTRIG/INCK low, XCLR low, wait >= 150 us, then 3V3 -> 2V9 -> 1V8 -> 1V1
//  * trigger fan-out: XTRIG_L/XTRIG_R follow TRIG_IN combinationally (skew = routing only)
//    while READY; held LOW otherwise (no back-powering of unpowered sensors)
//  * STATUS = READY (to the adapter's GPIO expander)
//  * aggregator reset held until the sensors are up
`timescale 1ns / 1ps
`default_nettype none

module stereo_ctrl #(
    parameter integer CLK_HZ    = 74_250_000,
    parameter integer T_STEP_US = 2000,     // between rails (> CT ramp)
    parameter integer T_SETTLE_US = 5000,   // all rails up -> XCLR release
    parameter integer T_INCK_US = 100,      // XCLR high -> INCK enable (>= 1 us)
    parameter integer T_READY_US = 1000,    // INCK -> READY (first I2C >= 20 us)
    parameter integer T_OFF_US  = 200       // XCLR low -> first rail off (>= 150 us)
) (
    input  wire clk,
    input  wire pwr_en_in,      // from FPC (async)
    input  wire trig_in,        // from FPC, active low, idle high
    output reg  en_1v1,
    output reg  en_1v8,
    output reg  en_2v9,
    output reg  en_3v3,
    output reg  xclr,           // to both sensors (through 10R)
    output reg  inck_oe,        // LMK1C1102 OE -> INCK_L / INCK_R
    output wire xtrig_l,
    output wire xtrig_r,
    output wire status,
    output wire agg_rst_n       // release the CSI-2 aggregator once sensors run
);
    localparam integer CYC_US = CLK_HZ / 1_000_000;

    // ---------------------------------------------------- input sync + filter
    reg [2:0] en_sync = 3'b000;
    always @(posedge clk) en_sync <= {en_sync[1:0], pwr_en_in};
    wire en_req = en_sync[2];

    // ---------------------------------------------------- state machine
    localparam [3:0] S_OFF = 4'd0, S_1V1 = 4'd1, S_1V8 = 4'd2, S_2V9 = 4'd3, S_3V3 = 4'd4,
                     S_XCLR = 4'd5, S_INCK = 4'd6, S_READY = 4'd7,
                     S_D_XCLR = 4'd8, S_D_3V3 = 4'd9, S_D_2V9 = 4'd10, S_D_1V8 = 4'd11,
                     S_D_1V1 = 4'd12;
    reg [3:0]  state = S_OFF;
    reg [31:0] timer = 32'd0;
    reg        ready = 1'b0;

    wire tmo = (timer == 32'd0);

    function [31:0] us;
        input integer t;
        us = t * CYC_US;
    endfunction

    initial begin
        en_1v1 = 1'b0; en_1v8 = 1'b0; en_2v9 = 1'b0; en_3v3 = 1'b0;
        xclr = 1'b0; inck_oe = 1'b0;
    end

    always @(posedge clk) begin
        if (!tmo)
            timer <= timer - 32'd1;
        case (state)
            S_OFF:   if (en_req) begin en_1v1 <= 1'b1; timer <= us(T_STEP_US); state <= S_1V1; end
            // aborts jump into the ordered shutdown at the highest rail that is on
            // (S_D_x switches the NEXT lower rail off when its timer expires)
            S_1V1:   if (!en_req) begin timer <= 32'd0; state <= S_D_1V8; end
                     else if (tmo) begin en_1v8 <= 1'b1; timer <= us(T_STEP_US); state <= S_1V8; end
            S_1V8:   if (!en_req) begin timer <= 32'd0; state <= S_D_2V9; end
                     else if (tmo) begin en_2v9 <= 1'b1; timer <= us(T_STEP_US); state <= S_2V9; end
            S_2V9:   if (!en_req) begin timer <= 32'd0; state <= S_D_3V3; end
                     else if (tmo) begin en_3v3 <= 1'b1; timer <= us(T_SETTLE_US); state <= S_3V3; end
            S_3V3:   if (!en_req) begin timer <= us(T_OFF_US); state <= S_D_XCLR; end
                     else if (tmo) begin xclr <= 1'b1; timer <= us(T_INCK_US); state <= S_XCLR; end
            S_XCLR:  if (!en_req) begin xclr <= 1'b0; timer <= us(T_OFF_US); state <= S_D_XCLR; end
                     else if (tmo) begin inck_oe <= 1'b1; timer <= us(T_READY_US); state <= S_INCK; end
            S_INCK:  if (!en_req) begin inck_oe <= 1'b0; xclr <= 1'b0; timer <= us(T_OFF_US); state <= S_D_XCLR; end
                     else if (tmo) begin ready <= 1'b1; state <= S_READY; end
            S_READY: if (!en_req) begin
                         ready <= 1'b0; inck_oe <= 1'b0; xclr <= 1'b0;
                         timer <= us(T_OFF_US); state <= S_D_XCLR;
                     end
            // ---- power-down (reverse order), DS 17.3
            S_D_XCLR: if (tmo) begin en_3v3 <= 1'b0; timer <= us(T_STEP_US); state <= S_D_3V3; end
            S_D_3V3:  if (tmo) begin en_2v9 <= 1'b0; timer <= us(T_STEP_US); state <= S_D_2V9; end
            S_D_2V9:  if (tmo) begin en_1v8 <= 1'b0; timer <= us(T_STEP_US); state <= S_D_1V8; end
            S_D_1V8:  if (tmo) begin en_1v1 <= 1'b0; timer <= us(T_STEP_US); state <= S_D_1V1; end
            S_D_1V1:  if (tmo) state <= S_OFF;
            default:  state <= S_OFF;
        endcase
    end

    // trigger: same edge to both sensors, low while not ready
    assign xtrig_l   = ready & trig_in;
    assign xtrig_r   = ready & trig_in;
    assign status    = ready;
    assign agg_rst_n = ready;
endmodule

`default_nettype wire
