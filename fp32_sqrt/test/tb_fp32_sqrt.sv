// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0

module FP32SqrtTB;
    parameter integer RANDOM_CYCLES = 200000;
    parameter integer MONOTONIC_SAMPLES = 200000;

    logic [31:0] x;
    logic [31:0] result;
    integer issue;
    integer random_seed;
    integer checked_count;
    integer rne_count;
    integer faithful_alternative_count;
    integer monotonic_count;
    integer unsigned max_ulp;
    logic [31:0] previous_result;

    import "DPI-C" function int unsigned fp32_sqrt_ref(
        input int unsigned input_bits
    );
    import "DPI-C" function longint unsigned fp32_sqrt_faithful_bounds(
        input int unsigned input_bits
    );

    FP32Sqrt dut (
        .x(x),
        .result(result)
    );

    function automatic logic is_nan(input logic [31:0] value);
        is_nan = value[30:23] == 8'hff && value[22:0] != 0;
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
            expected = fp32_sqrt_ref(input_bits);
            bounds = fp32_sqrt_faithful_bounds(input_bits);
            lower = bounds[31:0];
            upper = bounds[63:32];

            if (is_nan(expected)) begin
                if (result != 32'h7fc00000)
                    $fatal(1, "NaN規約違反: x=%h actual=%h", input_bits, result);
                ulp = 0;
            end else begin
                ulp = result >= expected ? result - expected : expected - result;
                if (result != lower && result != upper)
                    $fatal(1, "faithful/FTZ規約違反: x=%h actual=%h lower=%h upper=%h",
                           input_bits, result, lower, upper);
            end

            checked_count = checked_count + 1;
            if (ulp == 0)
                rne_count = rne_count + 1;
            else
                faithful_alternative_count = faithful_alternative_count + 1;
            if (ulp > max_ulp)
                max_ulp = ulp;
            if (ulp > 1)
                $fatal(1, "1 step超過: x=%h actual=%h expected=%h ulp=%0d",
                       input_bits, result, expected, ulp);
        end
    endtask

    initial begin
        x = 0;
        random_seed = 32'h53515254; // ASCIIのSQRTに対応する固定seed
        random_seed = $urandom(random_seed);
        checked_count = 0;
        rne_count = 0;
        faithful_alternative_count = 0;
        monotonic_count = 0;
        max_ulp = 0;
        previous_result = 0;

        check_vector(32'h00000000); // +0 -> +0
        check_vector(32'h80000000); // -0 -> -0
        check_vector(32'h00000001); // 正のsubnormalは+0として扱う
        check_vector(32'h007fffff);
        check_vector(32'h80000001); // 負のsubnormalは-0として扱う
        check_vector(32'h807fffff);
        check_vector(32'h00800000); // 最小normal
        check_vector(32'h3e800000); // 0.25 -> 0.5
        check_vector(32'h3f000000); // 0.5
        check_vector(32'h3f800000); // 1.0 -> 1.0
        check_vector(32'h40000000); // 2.0
        check_vector(32'h40800000); // 4.0 -> 2.0
        check_vector(32'h7f7fffff); // 最大有限入力
        check_vector(32'h7f800000); // +Inf -> +Inf
        check_vector(32'hbf800000); // 負のnormal -> qNaN
        check_vector(32'hff7fffff);
        check_vector(32'hff800000); // -Inf -> qNaN
        check_vector(32'h7fc00001); // NaN -> canonical qNaN
        check_vector(32'hffc00001);

        // 指数field全体と、仮数の端・中央を明示的に通す。
        for (issue = 0; issue < 256; issue = issue + 1) begin
            check_vector({ 1'b0, 8'(issue), 23'h000000 });
            check_vector({ 1'b0, 8'(issue), 23'h400000 });
            check_vector({ 1'b0, 8'(issue), 23'h7fffff });
            check_vector({ 1'b1, 8'(issue), 23'h000000 });
            check_vector({ 1'b1, 8'(issue), 23'h400000 });
            check_vector({ 1'b1, 8'(issue), 23'h7fffff });
        end

        for (issue = 0; issue < RANDOM_CYCLES; issue = issue + 1) begin
            logic [31:0] random_bits;
            random_bits = $urandom;
            if (issue[0]) begin
                random_bits[30:23] = 8'($urandom_range(1, 254));
                random_bits[31] = 1'($urandom_range(0, 1));
            end
            check_vector(random_bits);
        end

        // +0から+Infを等間隔に標本化し、出力が単調非減少か調べる。
        for (issue = 0; issue < MONOTONIC_SAMPLES; issue = issue + 1) begin
            longint unsigned numerator;
            numerator = 64'(issue) * 64'h000000007f800000;
            x = 32'(numerator / (64'(MONOTONIC_SAMPLES) - 64'd1));
            #1;
            if (issue != 0 && result < previous_result)
                $fatal(1, "単調性違反: x=%h previous=%h actual=%h",
                       x, previous_result, result);
            previous_result = result;
            monotonic_count = monotonic_count + 1;
        end

        $display("PASS: checked=%0d rne=%0d alternative=%0d max_ulp=%0d monotonic=%0d",
                 checked_count, rne_count, faithful_alternative_count,
                 max_ulp, monotonic_count);
        $finish;
    end
endmodule
