// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0

module FP32Log2LiteTB;
    parameter integer RANDOM_CYCLES = 200000;
    parameter integer MONOTONIC_SAMPLES = 200000;

    logic [31:0] x;
    logic [31:0] result;
    integer issue;
    integer random_seed;
    integer checked_count;
    integer correct_count;
    integer monotonic_count;
    longint unsigned max_ulp;
    real max_abs_error_units;
    logic [31:0] previous_result;
    logic [31:0] worst_input;

    import "DPI-C" function int unsigned fp32_log2_lite_ref(
        input int unsigned input_bits
    );
    import "DPI-C" function real fp32_log2_lite_abs_error_units(
        input int unsigned input_bits,
        input int unsigned actual_bits
    );

    FP32Log2Lite dut(.x(x), .result(result));

    function automatic logic is_nan(input logic [31:0] value);
        is_nan = value[30:23] == 8'hff && value[22:0] != 0;
    endfunction

    function automatic logic [31:0] ordered(input logic [31:0] value);
        ordered = value[31] ? ~value : (value ^ 32'h80000000);
    endfunction

    task automatic check_vector(input logic [31:0] input_bits);
        logic [31:0] expected;
        logic [31:0] actual_key;
        logic [31:0] expected_key;
        longint unsigned ulp;
        real abs_error_units;
        begin
            x = input_bits;
            #1;
            expected = fp32_log2_lite_ref(input_bits);
            checked_count = checked_count+1;
            if (is_nan(expected)) begin
                if (!is_nan(result))
                    $fatal(1, "NaN分類不一致: x=%h actual=%h", input_bits, result);
                correct_count = correct_count+1;
            end else if (expected[30:23] == 8'hff) begin
                if (result != expected)
                    $fatal(1, "Inf分類不一致: x=%h actual=%h expected=%h",
                           input_bits, result, expected);
                correct_count = correct_count+1;
            end else begin
                if (is_nan(result) || result[30:23] == 8'hff)
                    $fatal(1, "有限値分類不一致: x=%h actual=%h expected=%h",
                           input_bits, result, expected);
                actual_key = ordered(result);
                expected_key = ordered(expected);
                ulp = actual_key >= expected_key
                    ? 64'(actual_key)-64'(expected_key)
                    : 64'(expected_key)-64'(actual_key);
                abs_error_units = fp32_log2_lite_abs_error_units(input_bits, result);
                if (result == expected)
                    correct_count = correct_count+1;
                if (ulp > max_ulp) begin
                    max_ulp = ulp;
                    worst_input = input_bits;
                end
                if (abs_error_units > max_abs_error_units)
                    max_abs_error_units = abs_error_units;
                if (ulp > 2 && abs_error_units > 4.0)
                    $fatal(1, "誤差超過: x=%h actual=%h expected=%h ulp=%0d abs=%f",
                           input_bits, result, expected, ulp, abs_error_units);
            end
        end
    endtask

    initial begin
        x = 0;
        random_seed = 32'h4c4f4732;
        random_seed = $urandom(random_seed);
        checked_count = 0;
        correct_count = 0;
        monotonic_count = 0;
        max_ulp = 0;
        max_abs_error_units = 0.0;
        previous_result = 32'hff800000;
        worst_input = 0;

        check_vector(32'h00000000);
        check_vector(32'h80000000);
        check_vector(32'h00000001);
        check_vector(32'h007fffff);
        check_vector(32'h80000001);
        check_vector(32'h807fffff);
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

        for (issue = -126; issue <= 127; issue = issue+1)
            check_vector(32'((issue+127) << 23));

        for (issue = 0; issue < RANDOM_CYCLES; issue = issue+1) begin
            logic [31:0] random_bits;
            random_bits = $urandom;
            if (issue[0]) begin
                random_bits[31] = 1'b0;
                random_bits[30:23] = 8'($urandom_range(1, 254));
            end
            check_vector(random_bits);
        end

        for (issue = 0; issue < MONOTONIC_SAMPLES; issue = issue+1) begin
            logic [31:0] positive_input;
            positive_input = 32'((64'(issue)*64'h7f800000)
                / (64'(MONOTONIC_SAMPLES)-1));
            x = positive_input;
            #1;
            if (issue != 0 && ordered(result) < ordered(previous_result))
                $fatal(1, "単調性違反: x=%h previous=%h actual=%h",
                       positive_input, previous_result, result);
            previous_result = result;
            monotonic_count = monotonic_count+1;
        end

        $display("PASS: checked=%0d RNE_match=%0d max_ulp=%0d max_abs=%f monotonic=%0d",
                 checked_count, correct_count, max_ulp,
                 max_abs_error_units, monotonic_count);
        $display("WORST: x=%h", worst_input);
        $finish;
    end
endmodule
