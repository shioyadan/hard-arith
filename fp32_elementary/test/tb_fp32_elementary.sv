// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0

module FP32ElementaryTB;
    parameter integer RANDOM_CYCLES = 2000;
    parameter integer MONOTONIC_SAMPLES = 2000;
    localparam integer FUNCTION_COUNT = 7;
    localparam integer DIRECTED_COUNT = 24;

    logic [31:0] x;
    logic [6:0] op;
    wire [31:0] result;
    integer issue;
    integer function_index;
    integer checked_count [0:FUNCTION_COUNT-1];
    integer exact_count [0:FUNCTION_COUNT-1];
    integer monotonic_violations [0:FUNCTION_COUNT-1];
    longint unsigned max_ulp [0:FUNCTION_COUNT-1];
    real max_abs_error_units [0:FUNCTION_COUNT-1];
    logic [31:0] previous_result [0:FUNCTION_COUNT-1];
    logic [31:0] worst_input [0:FUNCTION_COUNT-1];
    logic [31:0] worst_actual [0:FUNCTION_COUNT-1];
    logic [31:0] worst_expected [0:FUNCTION_COUNT-1];

    import "DPI-C" function int unsigned fp32_elementary_ref(
        input int unsigned input_bits,
        input int unsigned function_code
    );
    import "DPI-C" function real fp32_elementary_abs_error_units(
        input int unsigned input_bits,
        input int unsigned function_code,
        input int unsigned actual_bits
    );
    import "DPI-C" function int unsigned fp32_elementary_test_input(
        input int unsigned function_index,
        input int unsigned ordinal
    );
    import "DPI-C" function int unsigned fp32_elementary_monotonic_input(
        input int unsigned function_index,
        input int unsigned ordinal,
        input int unsigned count
    );

    FP32Elementary dut(.x(x), .op(op), .result(result));

    function automatic logic is_nan(input logic [31:0] value);
        is_nan = value[30:23] == 8'hff && value[22:0] != 0;
    endfunction

    function automatic logic is_inf(input logic [31:0] value);
        is_inf = value[30:23] == 8'hff && value[22:0] == 0;
    endfunction

    function automatic logic [31:0] ordered_key(input logic [31:0] value);
        ordered_key = value[31] ? ~value : (value^32'h80000000);
    endfunction

    function automatic logic [31:0] directed_input(input integer index);
        case (index)
            0: directed_input = 32'h00000000;
            1: directed_input = 32'h80000000;
            2: directed_input = 32'h00000001;
            3: directed_input = 32'h007fffff;
            4: directed_input = 32'h00800000;
            5: directed_input = 32'h3e800000;
            6: directed_input = 32'h3f000000;
            7: directed_input = 32'h3f800000;
            8: directed_input = 32'h40000000;
            9: directed_input = 32'h40400000;
            10: directed_input = 32'h40800000;
            11: directed_input = 32'hbf000000;
            12: directed_input = 32'hbf800000;
            13: directed_input = 32'hc0000000;
            14: directed_input = 32'h42fe0000;
            15: directed_input = 32'h43000000;
            16: directed_input = 32'hc3160000;
            17: directed_input = 32'hc3170000;
            18: directed_input = 32'h7f7fffff;
            19: directed_input = 32'hff7fffff;
            20: directed_input = 32'h7f800000;
            21: directed_input = 32'hff800000;
            22: directed_input = 32'h7fc00001;
            default: directed_input = 32'hffc00001;
        endcase
    endfunction

    task automatic check_vector(input integer index, input logic [31:0] input_bits);
        logic [31:0] expected;
        logic [31:0] actual_key;
        logic [31:0] expected_key;
        longint unsigned ulp;
        real abs_error;
        begin
            x = input_bits;
            op = 7'(1 << index);
            #1;
            expected = fp32_elementary_ref(input_bits, {25'b0, op});
            checked_count[index] = checked_count[index]+1;
            if (is_nan(expected)) begin
                if (!is_nan(result))
                    $fatal(1, "NaN分類不一致: op=%h x=%h actual=%h", op, x, result);
                exact_count[index] = exact_count[index]+1;
            end else if (is_inf(expected)) begin
                if (result != expected)
                    $fatal(1, "Inf分類不一致: op=%h x=%h actual=%h expected=%h",
                           op, x, result, expected);
                exact_count[index] = exact_count[index]+1;
            end else begin
                if (is_nan(result) || is_inf(result))
                    $fatal(1, "有限値分類不一致: op=%h x=%h actual=%h expected=%h",
                           op, x, result, expected);
                actual_key = ordered_key(result);
                expected_key = ordered_key(expected);
                ulp = actual_key >= expected_key
                    ? {32'b0, actual_key}-{32'b0, expected_key}
                    : {32'b0, expected_key}-{32'b0, actual_key};
                abs_error = fp32_elementary_abs_error_units(
                    input_bits, {25'b0, op}, result
                );
                if (ulp == 0)
                    exact_count[index] = exact_count[index]+1;
                if (ulp > max_ulp[index]) begin
                    max_ulp[index] = ulp;
                    worst_input[index] = input_bits;
                    worst_actual[index] = result;
                    worst_expected[index] = expected;
                end
                if (abs_error > max_abs_error_units[index])
                    max_abs_error_units[index] = abs_error;
                if ((index == 0 || index == 1 || index == 2 || index == 3)
                    && ulp > 1)
                    $fatal(1, "ULP超過: op=%h x=%h actual=%h expected=%h ulp=%0d",
                           op, x, result, expected, ulp);
                if (index == 4 && ulp > 2 && abs_error > 4.0)
                    $fatal(1, "log2誤差超過: x=%h actual=%h expected=%h ulp=%0d abs=%f",
                           x, result, expected, ulp, abs_error);
                if ((index == 5 || index == 6) && abs_error > 4.0)
                    $fatal(1, "sincos誤差超過: op=%h x=%h actual=%h expected=%h abs=%f",
                           op, x, result, expected, abs_error);
            end
        end
    endtask

    initial begin
        x = 0;
        op = 7'b0000001;
        for (function_index = 0; function_index < FUNCTION_COUNT;
             function_index = function_index+1) begin
            checked_count[function_index] = 0;
            exact_count[function_index] = 0;
            max_ulp[function_index] = 0;
            max_abs_error_units[function_index] = 0.0;
            monotonic_violations[function_index] = 0;
            previous_result[function_index] = 0;
            worst_input[function_index] = 0;
            worst_actual[function_index] = 0;
            worst_expected[function_index] = 0;
        end

        for (issue = 0; issue < DIRECTED_COUNT; issue = issue+1)
            for (function_index = 0; function_index < FUNCTION_COUNT;
                 function_index = function_index+1)
                check_vector(function_index, directed_input(issue));

        for (issue = 0; issue < RANDOM_CYCLES; issue = issue+1)
            for (function_index = 0; function_index < FUNCTION_COUNT;
                 function_index = function_index+1)
                check_vector(function_index,
                    fp32_elementary_test_input(function_index, issue));

        for (issue = 0; issue < MONOTONIC_SAMPLES; issue = issue+1) begin
            for (function_index = 0; function_index < FUNCTION_COUNT;
                 function_index = function_index+1) begin
                x = fp32_elementary_monotonic_input(
                    function_index, issue, MONOTONIC_SAMPLES);
                op = 7'(1 << function_index);
                #1;
                if (issue != 0) begin
                    if ((function_index == 1 || function_index == 2
                         || function_index == 6)
                        && ordered_key(result) > ordered_key(previous_result[function_index]))
                        monotonic_violations[function_index] =
                            monotonic_violations[function_index]+1;
                    if ((function_index == 0 || function_index == 3
                         || function_index == 4 || function_index == 5)
                        && ordered_key(result) < ordered_key(previous_result[function_index]))
                        monotonic_violations[function_index] =
                            monotonic_violations[function_index]+1;
                end
                previous_result[function_index] = result;
            end
        end

        for (function_index = 0; function_index < FUNCTION_COUNT;
             function_index = function_index+1) begin
            $display("FUNCTION: code=%04h checked=%0d exact=%0d max_ulp=%0d max_abs_2^-23=%f monotonic_violations=%0d",
                     16'(1 << function_index), checked_count[function_index],
                     exact_count[function_index], max_ulp[function_index],
                     max_abs_error_units[function_index],
                     monotonic_violations[function_index]);
            if (function_index != 5 && function_index != 6
                && monotonic_violations[function_index] != 0)
                $fatal(1, "単調性違反: op=%h count=%0d",
                       16'(1 << function_index),
                       monotonic_violations[function_index]);
            if (max_ulp[function_index] != 0)
                $display("WORST: code=%04h x=%h actual=%h expected=%h",
                         16'(1 << function_index), worst_input[function_index],
                         worst_actual[function_index], worst_expected[function_index]);
        end
        $display("PASS: functions=7 vectors_per_function=%0d monotonic_per_function=%0d",
                 DIRECTED_COUNT+RANDOM_CYCLES, MONOTONIC_SAMPLES);
        $finish;
    end
endmodule
