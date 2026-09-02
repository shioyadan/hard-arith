// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0

module FP32SinCosPiTB;
    parameter integer RANDOM_CYCLES = 200000;

    logic [31:0] x;
    logic select_cos;
    logic [31:0] result;
    integer issue;
    integer random_seed;
    integer checked_count;
    integer correct_count;
    integer faithful_count;
    integer unsigned max_ulp;
    logic [31:0] worst_input;
    logic worst_select_cos;

    import "DPI-C" function int unsigned fp32_sincospi_ref(
        input int unsigned input_bits,
        input int unsigned select_cos_value
    );
    import "DPI-C" function longint unsigned fp32_sincospi_faithful_bounds(
        input int unsigned input_bits,
        input int unsigned select_cos_value
    );

    FP32SinCosPi dut (
        .x(x),
        .select_cos(select_cos),
        .result(result)
    );

    function automatic logic is_nan(input logic [31:0] value);
        is_nan = value[30:23] == 8'hff && value[22:0] != 0;
    endfunction

    function automatic logic [31:0] ordered(input logic [31:0] value);
        ordered = value[31] ? ~value : (value ^ 32'h80000000);
    endfunction

    function automatic integer unsigned ulp_distance(
        input logic [31:0] actual,
        input logic [31:0] expected
    );
        logic [31:0] actual_ordered;
        logic [31:0] expected_ordered;
        begin
            if (is_nan(actual) && is_nan(expected)) begin
                ulp_distance = 0;
            end else begin
                actual_ordered = ordered(actual);
                expected_ordered = ordered(expected);
                ulp_distance = actual_ordered >= expected_ordered
                    ? actual_ordered-expected_ordered
                    : expected_ordered-actual_ordered;
            end
        end
    endfunction

    task automatic check_vector(
        input logic [31:0] input_bits,
        input logic select_cos_value
    );
        logic [31:0] expected;
        logic [63:0] bounds;
        integer unsigned distance;
        begin
            x = input_bits;
            select_cos = select_cos_value;
            #1;
            expected = fp32_sincospi_ref(input_bits, 32'(select_cos_value));
            bounds = fp32_sincospi_faithful_bounds(
                input_bits, 32'(select_cos_value)
            );
            distance = ulp_distance(result, expected);
            checked_count = checked_count+1;
            if (distance == 0)
                correct_count = correct_count+1;
            if (result == bounds[31:0] || result == bounds[63:32]
                || (is_nan(result) && is_nan(expected))) begin
                faithful_count = faithful_count+1;
            end else begin
                $fatal(1, "faithful違反: cos=%0d x=%h actual=%h expected=%h lower=%h upper=%h",
                       select_cos_value, input_bits, result, expected,
                       bounds[31:0], bounds[63:32]);
            end
            if (distance > max_ulp) begin
                max_ulp = distance;
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
        random_seed = 32'h53434f53;
        random_seed = $urandom(random_seed);
        checked_count = 0;
        correct_count = 0;
        faithful_count = 0;
        max_ulp = 0;
        worst_input = 0;
        worst_select_cos = 0;

        check_both(32'h00000000);
        check_both(32'h80000000);
        check_both(32'h00000001);
        check_both(32'h007fffff);
        check_both(32'h00800000);
        check_both(32'h3a800000);
        check_both(32'h3b000000);
        check_both(32'h3b7fffff);
        check_both(32'h3b800000);
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

        $display("PASS: checked=%0d correct=%0d faithful=%0d max_ulp=%0d",
                 checked_count, correct_count, faithful_count, max_ulp);
        $display("WORST: cos=%0d x=%h", worst_select_cos, worst_input);
        $finish;
    end
endmodule
