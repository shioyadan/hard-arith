// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0

module FP32SinCosPiLiteTB;
    parameter integer RANDOM_CYCLES = 200000;
    parameter real MAX_ABS_ERROR_UNITS = 4.000001;

    logic [31:0] x;
    logic select_cos;
    logic [31:0] result;
    integer issue;
    integer random_seed;
    integer checked_count;
    integer correct_count;
    real max_error_units;
    logic [31:0] worst_input;
    logic worst_select_cos;

    import "DPI-C" function int unsigned fp32_sincospi_ref(
        input int unsigned input_bits,
        input int unsigned select_cos_value
    );
    import "DPI-C" function real fp32_sincospi_abs_error_units(
        input int unsigned input_bits,
        input int unsigned select_cos_value,
        input int unsigned actual_bits
    );

    FP32SinCosPiLite dut (
        .x(x),
        .select_cos(select_cos),
        .result(result)
    );

    task automatic check_vector(
        input logic [31:0] input_bits,
        input logic select_cos_value
    );
        logic [31:0] expected;
        real error_units;
        begin
            x = input_bits;
            select_cos = select_cos_value;
            #1;
            expected = fp32_sincospi_ref(input_bits, 32'(select_cos_value));
            error_units = fp32_sincospi_abs_error_units(
                input_bits, 32'(select_cos_value), result
            );
            checked_count = checked_count+1;
            if (result == expected)
                correct_count = correct_count+1;
            if (!(error_units <= MAX_ABS_ERROR_UNITS)) begin
                $fatal(1, "絶対誤差違反: cos=%0d x=%h actual=%h expected=%h error=%0.9f*2^-23",
                       select_cos_value, input_bits, result, expected,
                       error_units);
            end
            if (error_units > max_error_units) begin
                max_error_units = error_units;
                worst_input = input_bits;
                worst_select_cos = select_cos_value;
            end
        end
    endtask

    task automatic check_both(input logic [31:0] input_bits);
        begin
            check_vector(input_bits, 1'b0);
            check_vector(input_bits, 1'b1);
        end
    endtask

    initial begin
        x = 0;
        select_cos = 0;
        random_seed = 32'h4c495445;
        random_seed = $urandom(random_seed);
        checked_count = 0;
        correct_count = 0;
        max_error_units = 0.0;
        worst_input = 0;
        worst_select_cos = 0;

        check_both(32'h00000000);
        check_both(32'h80000000);
        check_both(32'h00000001);
        check_both(32'h007fffff);
        check_both(32'h00800000);
        check_both(32'h32800000);
        check_both(32'h32ffffff);
        check_both(32'h33000000);
        check_both(32'h3e7fffff);
        check_both(32'h3e800000);
        check_both(32'h3effffff);
        check_both(32'h3f000000);
        check_both(32'h3f000001);
        check_both(32'h3f7fffff);
        check_both(32'h3f800000);
        check_both(32'h3fc00000);
        check_both(32'h40000000);
        check_both(32'h40200000);
        check_both(32'h4affffff);
        check_both(32'h4b000000);
        check_both(32'h4b7fffff);
        check_both(32'h4b800000);
        check_both(32'h7f7fffff);
        check_both(32'h7f800000);
        check_both(32'hff800000);
        check_both(32'h7fc00001);

        for (issue = -149; issue <= 23; issue = issue+1) begin
            logic [31:0] power_bits;
            if (issue >= -126)
                power_bits = 32'((issue+127) << 23);
            else
                power_bits = 32'(1 << (issue+149));
            check_both(power_bits);
            check_both(power_bits | 32'h80000000);
        end

        for (issue = 0; issue < RANDOM_CYCLES; issue = issue+1) begin
            logic [31:0] random_bits;
            random_bits = $urandom;
            check_both(random_bits);
        end

        $display("PASS: checked=%0d RNE_match=%0d max_abs_error=%0.9f*2^-23",
                 checked_count, correct_count, max_error_units);
        $display("WORST: cos=%0d x=%h", worst_select_cos, worst_input);
        $finish;
    end
endmodule
