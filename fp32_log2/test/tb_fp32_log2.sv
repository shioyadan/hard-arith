// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0

module FP32Log2TB;
    parameter integer RANDOM_CYCLES = 200000;
    parameter integer MONOTONIC_SAMPLES = 200000;

    logic [31:0] x;
    logic [31:0] result;
    integer issue;
    integer random_seed;
    integer checked_count;
    integer correct_count;
    integer faithful_count;
    integer monotonic_count;
    integer unsigned max_ulp;
    logic [31:0] previous_result;
    logic [31:0] worst_input;

    import "DPI-C" function int unsigned fp32_log2_ref(
        input int unsigned input_bits
    );
    import "DPI-C" function longint unsigned fp32_log2_faithful_bounds(
        input int unsigned input_bits
    );

    FP32Log2 dut (
        .x(x),
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

    task automatic check_vector(input logic [31:0] input_bits);
        logic [31:0] expected;
        logic [63:0] bounds;
        integer unsigned distance;
        begin
            x = input_bits;
            #1;
            expected = fp32_log2_ref(input_bits);
            bounds = fp32_log2_faithful_bounds(input_bits);
            distance = ulp_distance(result, expected);
            checked_count = checked_count+1;

            if (distance == 0)
                correct_count = correct_count+1;
            if (result == bounds[31:0] || result == bounds[63:32] ||
                (is_nan(result) && is_nan(expected)))
                faithful_count = faithful_count+1;
            else
                $fatal(1, "faithful違反: x=%h actual=%h expected=%h lower=%h upper=%h",
                       input_bits, result, expected, bounds[31:0], bounds[63:32]);

            if (distance > max_ulp) begin
                max_ulp = distance;
                worst_input = input_bits;
            end
        end
    endtask

    initial begin
        x = 0;
        random_seed = 32'h004c4f47;
        random_seed = $urandom(random_seed);
        checked_count = 0;
        correct_count = 0;
        faithful_count = 0;
        monotonic_count = 0;
        max_ulp = 0;
        previous_result = 32'hff800000;
        worst_input = 0;

        check_vector(32'h00000000);
        check_vector(32'h80000000);
        check_vector(32'h00000001);
        check_vector(32'h007fffff);
        check_vector(32'h00800000);
        check_vector(32'h3f7ffffe);
        check_vector(32'h3f7fffff);
        check_vector(32'h3f800000);
        check_vector(32'h3f800001);
        check_vector(32'h3f800002);
        check_vector(32'h3fb504f2);
        check_vector(32'h3fb504f3);
        check_vector(32'h3fb504f4);
        check_vector(32'h40000000);
        check_vector(32'h7f7fffff);
        check_vector(32'h7f800000);
        check_vector(32'hff800000);
        check_vector(32'hbf800000);
        check_vector(32'h7fc00001);

        for (issue = -149; issue <= 127; issue = issue+1) begin
            logic [31:0] power_bits;
            if (issue >= -126)
                power_bits = 32'((issue+127) << 23);
            else
                power_bits = 32'(1 << (issue+149));
            check_vector(power_bits);
        end

        for (issue = 0; issue < RANDOM_CYCLES; issue = issue+1) begin
            logic [31:0] random_bits;
            random_bits = $urandom;
            if (issue[0]) begin
                random_bits[31] = 1'b0;
                random_bits[30:23] = 8'($urandom_range(0, 254));
            end
            check_vector(random_bits);
        end

        for (issue = 0; issue < MONOTONIC_SAMPLES; issue = issue+1) begin
            logic [31:0] positive_input;
            positive_input = 32'd1
                + 32'((64'(issue) * 64'h7f7ffffe) / (64'(MONOTONIC_SAMPLES)-1));
            x = positive_input;
            #1;
            if (issue != 0 && ordered(result) < ordered(previous_result))
                $fatal(1, "単調性違反: x=%h previous=%h actual=%h",
                       positive_input, previous_result, result);
            previous_result = result;
            monotonic_count = monotonic_count+1;
        end

        $display("PASS: checked=%0d correct=%0d faithful=%0d max_ulp=%0d monotonic=%0d",
                 checked_count, correct_count, faithful_count, max_ulp,
                 monotonic_count);
        $display("WORST: x=%h", worst_input);
        $finish;
    end
endmodule
