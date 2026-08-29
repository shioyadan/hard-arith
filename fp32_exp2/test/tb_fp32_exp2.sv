// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0

module FP32Exp2TB;
    parameter integer RANDOM_CYCLES = 200000;
    parameter integer BOUNDARY_STRIDE = 1;
    parameter integer MONOTONIC_SAMPLES = 200000;

    logic [31:0] x;
    logic [31:0] result;
    integer issue;
    integer random_seed;
    integer checked_count;
    integer correct_count;
    integer one_ulp_count;
    integer faithful_count;
    integer monotonic_count;
    logic [31:0] worst_input;
    logic [31:0] worst_actual;
    logic [31:0] worst_expected;
    integer unsigned max_ulp;
    logic [31:0] previous_result;
    longint unsigned monotonic_ordinal;

    import "DPI-C" function int unsigned fp32_exp2_ref(
        input int unsigned input_bits
    );
    import "DPI-C" function longint unsigned fp32_exp2_faithful_bounds(
        input int unsigned input_bits
    );
    import "DPI-C" function int unsigned fp32_exp2_reduction_boundary(
        input int index
    );

    FP32Exp2 dut (
        .x(x),
        .result(result)
    );

    function automatic logic is_nan(input logic [31:0] value);
        is_nan = value[30:23] == 8'hff && value[22:0] != 0;
    endfunction

    function automatic logic [31:0] input_from_ordinal(
        input logic [29:0] ordinal
    );
        logic [28:0] rank;
        begin
            if (ordinal < 30'h10800000) begin
                rank = 29'h107fffff - ordinal[28:0];
                input_from_ordinal = {
                    1'b1, 8'd102 + { 2'b0, rank[28:23] }, rank[22:0]
                };
            end else begin
                rank = 29'(ordinal - 30'h10800000);
                input_from_ordinal = {
                    1'b0, 8'd102 + { 2'b0, rank[28:23] }, rank[22:0]
                };
            end
        end
    endfunction

    task automatic check_vector(input logic [31:0] input_bits);
        logic [31:0] expected;
        logic [63:0] bounds;
        logic [31:0] lower;
        logic [31:0] upper;
        integer unsigned ulp;
        begin
            x = input_bits;
            #1;
            expected = fp32_exp2_ref(input_bits);
            if (is_nan(result) && is_nan(expected))
                ulp = 0;
            else if (result >= expected)
                ulp = result - expected;
            else
                ulp = expected - result;

            checked_count = checked_count + 1;
            if (ulp == 0)
                correct_count = correct_count + 1;
            if (ulp == 1)
                one_ulp_count = one_ulp_count + 1;
            if (ulp > max_ulp) begin
                max_ulp = ulp;
                worst_input = input_bits;
                worst_actual = result;
                worst_expected = expected;
            end
            if (ulp > 1)
                $fatal(1, "1 ULP超過: x=%h actual=%h expected=%h ulp=%0d",
                       input_bits, result, expected, ulp);

            bounds = fp32_exp2_faithful_bounds(input_bits);
            lower = bounds[31:0];
            upper = bounds[63:32];
            if (is_nan(result) && is_nan(lower))
                faithful_count = faithful_count + 1;
            else if (result == lower || result == upper)
                faithful_count = faithful_count + 1;
            else
                $fatal(1, "faithful違反: x=%h actual=%h lower=%h upper=%h",
                       input_bits, result, lower, upper);
        end
    endtask

    initial begin
        x = 0;
        random_seed = 32'h45585032;
        random_seed = $urandom(random_seed);
        checked_count = 0;
        correct_count = 0;
        one_ulp_count = 0;
        faithful_count = 0;
        monotonic_count = 0;
        max_ulp = 0;
        worst_input = 0;
        worst_actual = 0;
        worst_expected = 0;
        previous_result = 0;
        monotonic_ordinal = 0;

        check_vector(32'h00000000);
        check_vector(32'h80000000);
        check_vector(32'h00000001);
        check_vector(32'h007fffff);
        check_vector(32'h00800000);
        check_vector(32'h3f800000);
        check_vector(32'hbf800000);
        check_vector(32'h3e67ffff); // n=14から15への境界直前
        check_vector(32'h3e680000); // n=14から15への境界
        check_vector(32'h3e680001); // n=14から15への境界直後
        check_vector(32'h43000000); // +128: overflow境界
        check_vector(32'h42fe0000); // +127: 厳密な2の累乗
        check_vector(32'hc2fc0000); // -126: normal/subnormal境界
        check_vector(32'hc3150000); // -149: 最小subnormal
        check_vector(32'hc3160000); // -150: zeroとの中点
        check_vector(32'hc3170000); // -151: 完全underflow側
        check_vector(32'h7f7fffff);
        check_vector(32'hff7fffff);
        check_vector(32'h7f800000);
        check_vector(32'hff800000);
        check_vector(32'h7fc00001);

        for (issue = -9600; issue < 8192; issue = issue + BOUNDARY_STRIDE) begin
            logic [31:0] boundary;
            boundary = fp32_exp2_reduction_boundary(issue);
            check_vector(boundary - 1);
            check_vector(boundary);
            check_vector(boundary + 1);
        end

        for (issue = 0; issue < RANDOM_CYCLES; issue = issue + 1) begin
            logic [31:0] random_bits;
            random_bits = $urandom;
            if (issue[0]) begin
                random_bits[30:23] = 8'($urandom_range(96, 135));
                random_bits[31] = 1'($urandom_range(0, 1));
            end
            check_vector(random_bits);
        end

        for (issue = 0; issue < MONOTONIC_SAMPLES; issue = issue + 1) begin
            monotonic_ordinal =
                (64'(issue) * 64'd553648127) / (64'(MONOTONIC_SAMPLES) - 64'd1);
            x = input_from_ordinal(monotonic_ordinal[29:0]);
            #1;
            if (issue != 0 && result < previous_result)
                $fatal(1, "単調性違反: ordinal=%0d previous=%h actual=%h",
                       monotonic_ordinal, previous_result, result);
            previous_result = result;
            monotonic_count = monotonic_count + 1;
        end

        $display("PASS: checked=%0d correct=%0d one_ulp=%0d max_ulp=%0d faithful=%0d monotonic=%0d",
                 checked_count, correct_count, one_ulp_count, max_ulp,
                 faithful_count, monotonic_count);
        if (max_ulp != 0)
            $display("WORST: x=%h actual=%h expected=%h",
                     worst_input, worst_actual, worst_expected);
        $finish;
    end
endmodule
