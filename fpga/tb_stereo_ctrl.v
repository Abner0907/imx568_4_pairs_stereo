// tb_stereo_ctrl.v - self-checking testbench
//   iverilog -g2012 -o tb fpga/tb_stereo_ctrl.v fpga/stereo_ctrl.v && vvp tb
`timescale 1ns / 1ps
module tb_stereo_ctrl;
    reg clk = 0, pwr_en = 0, trig = 1;
    always #5 clk = ~clk;                       // 100 MHz, CLK_HZ scaled below

    wire e11, e18, e29, e33, xclr, oe, tl, tr, st, rstn;
    stereo_ctrl #(.CLK_HZ(10_000_000), .T_STEP_US(20), .T_SETTLE_US(50), .T_INCK_US(5),
                  .T_READY_US(10), .T_OFF_US(15))
        dut (.clk(clk), .pwr_en_in(pwr_en), .trig_in(trig), .en_1v1(e11), .en_1v8(e18),
             .en_2v9(e29), .en_3v3(e33), .xclr(xclr), .inck_oe(oe), .xtrig_l(tl),
             .xtrig_r(tr), .status(st), .agg_rst_n(rstn));

    integer errors = 0;
    // invariants checked every cycle: a higher rail never on without the lower ones,
    // XCLR / INCK / trigger never active unless all rails are on
    always @(posedge clk) begin
        if ((e18 & !e11) | (e29 & !e18) | (e33 & !e29)) begin
            $display("ERROR %0t: rail order violated %b%b%b%b", $time, e11, e18, e29, e33); errors = errors + 1;
        end
        if ((xclr | oe | tl | tr | st) & !(e11 & e18 & e29 & e33)) begin
            $display("ERROR %0t: control active with rails down", $time); errors = errors + 1;
        end
        if (oe & !xclr) begin
            $display("ERROR %0t: INCK enabled while XCLR low", $time); errors = errors + 1;
        end
        if (tl !== tr) begin
            $display("ERROR %0t: XTRIG_L != XTRIG_R", $time); errors = errors + 1;
        end
    end

    task wait_us(input integer n); begin repeat (n * 10) @(posedge clk); end endtask

    initial begin
        wait_us(5);
        // full power-up
        pwr_en = 1;
        wait_us(200);
        if (!st || !xclr || !oe) begin $display("ERROR: not ready after power-up"); errors = errors + 1; end
        // trigger passes through to both sensors
        trig = 0; @(posedge clk); #1;
        if (tl !== 0 || tr !== 0) begin $display("ERROR: trigger low not forwarded"); errors = errors + 1; end
        trig = 1; @(posedge clk); #1;
        if (tl !== 1) begin $display("ERROR: trigger high not forwarded"); errors = errors + 1; end
        // power-down
        pwr_en = 0;
        wait_us(150);
        if (e11 | e18 | e29 | e33 | st) begin $display("ERROR: not off after power-down"); errors = errors + 1; end
        // abort in the middle of the ramp (only 1V1 + 1V8 on)
        pwr_en = 1; wait_us(25); pwr_en = 0;
        wait_us(100);
        if (e11 | e18 | e29 | e33) begin $display("ERROR: abort left rails on"); errors = errors + 1; end
        // triggers while off must stay low
        trig = 0; wait_us(1); trig = 1; wait_us(1);
        if (errors == 0) $display("PASS"); else $display("FAIL (%0d errors)", errors);
        $finish;
    end
endmodule
