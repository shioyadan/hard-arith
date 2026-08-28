// Copyright 2026 Ryota Shioya
// SPDX-License-Identifier: Apache-2.0

module FP32RecipTB;
    parameter integer RANDOM_CYCLES = 200000;       // 固定seedで生成する乱数入力数
    parameter integer MONOTONIC_SAMPLES = 200000;   // 正領域から等間隔に取る単調性標本数

    logic [31:0] x;                                 // DUTへ与えるbinary32 bit pattern
    logic [31:0] result;                            // DUTが返すbinary32 bit pattern
    integer issue;                                  // test loopの位置
    integer index;                                  // table区間の位置
    integer random_seed;                            // 再現可能な乱数seed
    integer checked_count;                          // 参照値と比較した入力数
    integer correct_count;                          // RNE参照値と一致した入力数
    integer faithful_alternative_count;             // RNEとは異なるfaithful値だった入力数
    integer faithful_count;                         // normal結果でfaithfulだった入力数
    integer monotonic_count;                        // 単調性を比較した入力数
    integer symmetry_count;                         // 符号対称性を比較した入力数
    integer unsigned max_ulp;                       // RNE参照値からの最大step数
    logic [31:0] worst_input;                       // 最大step数を観測した入力
    logic [31:0] worst_actual;                      // そのときのDUT出力
    logic [31:0] worst_expected;                    // そのときのRNE参照値
    logic [31:0] previous_result;                   // 単調性検査の直前出力

    import "DPI-C" function int unsigned fp32_recip_ref(
        input int unsigned input_bits
    );
    import "DPI-C" function longint unsigned fp32_recip_faithful_bounds(
        input int unsigned input_bits
    );

    FP32Recip dut (
        .x(x),
        .result(result)
    );

    function automatic logic is_nan(input logic [31:0] value);
        is_nan = value[30:23] == 8'hff && value[22:0] != 0;
    endfunction

    function automatic logic [31:0] ordered_key(input logic [31:0] value);
        ordered_key = value[31] ? ~value : value | 32'h80000000;
    endfunction

    task automatic check_vector(input logic [31:0] input_bits);
        logic [31:0] expected;                      // exact整数除算から得たRNE参照値
        logic [63:0] bounds;                        // 厳密値を挟む二つのbinary32
        logic [31:0] lower;                         // faithful下限
        logic [31:0] upper;                         // faithful上限
        logic [31:0] actual_key;                    // ULP距離用に全順序へ写した出力
        logic [31:0] expected_key;                  // ULP距離用に全順序へ写した参照値
        integer unsigned ulp;                       // RNE参照値からのstep数
        begin
            x = input_bits;
            #1;
            expected = fp32_recip_ref(input_bits);
            bounds = fp32_recip_faithful_bounds(input_bits);
            lower = bounds[31:0];
            upper = bounds[63:32];

            if (is_nan(expected)) begin
                if (result != 32'h7fc00000)
                    $fatal(1, "NaN規約違反: x=%h actual=%h", input_bits, result);
                ulp = 0;
            end else begin
                actual_key = ordered_key(result);
                expected_key = ordered_key(expected);
                ulp = actual_key >= expected_key
                    ? actual_key - expected_key : expected_key - actual_key;
                if (result != lower && result != upper)
                    $fatal(1, "faithful/FTZ規約違反: x=%h actual=%h lower=%h upper=%h",
                           input_bits, result, lower, upper);
            end

            checked_count = checked_count + 1;
            if (ulp == 0)
                correct_count = correct_count + 1;
            else
                faithful_alternative_count = faithful_alternative_count + 1;
            if (expected[30:23] != 0 && expected[30:23] != 8'hff)
                faithful_count = faithful_count + 1;
            if (ulp > max_ulp) begin
                max_ulp = ulp;
                worst_input = input_bits;
                worst_actual = result;
                worst_expected = expected;
            end
            if (ulp > 1)
                $fatal(1, "1 step超過: x=%h actual=%h expected=%h ulp=%0d",
                       input_bits, result, expected, ulp);
        end
    endtask

    task automatic check_sign_pair(input logic [30:0] magnitude_bits);
        logic [31:0] positive_result;
        logic [31:0] negative_result;
        begin
            x = { 1'b0, magnitude_bits };
            #1;
            positive_result = result;
            x = { 1'b1, magnitude_bits };
            #1;
            negative_result = result;
            if (is_nan(positive_result)) begin
                if (negative_result != 32'h7fc00000)
                    $fatal(1, "NaN符号規約違反: x=%h actual=%h",
                           { 1'b1, magnitude_bits }, negative_result);
            end else if (negative_result != (positive_result | 32'h80000000)) begin
                $fatal(1, "符号対称性違反: |x|=%h positive=%h negative=%h",
                       magnitude_bits, positive_result, negative_result);
            end
            symmetry_count = symmetry_count + 1;
        end
    endtask

    initial begin
        x = 0;
        random_seed = 32'h00524350;                 // ASCIIのRCPに対応する固定seed
        random_seed = $urandom(random_seed);
        checked_count = 0;
        correct_count = 0;
        faithful_alternative_count = 0;
        faithful_count = 0;
        monotonic_count = 0;
        symmetry_count = 0;
        max_ulp = 0;
        worst_input = 0;
        worst_actual = 0;
        worst_expected = 0;
        previous_result = 0;

        check_vector(32'h00000000);                 // +0 -> +Inf
        check_vector(32'h80000000);                 // -0 -> -Inf
        check_vector(32'h00000001);                 // 最小subnormal入力はFTZ
        check_vector(32'h00200000);                 // 2^-128もFTZ入力として扱う
        check_vector(32'h007fffff);                 // 最大subnormal入力もFTZ
        check_vector(32'h00800000);                 // 最小normal -> 2^126
        check_vector(32'h3f000000);                 // 0.5 -> 2.0
        check_vector(32'h3f800000);                 // 1.0 -> 1.0
        check_vector(32'h3fc00000);                 // 1.5
        check_vector(32'h40000000);                 // 2.0 -> 0.5
        check_vector(32'h7e800000);                 // 2^126 -> 最小normal
        check_vector(32'h7e800001);                 // normal出力側のFTZ境界直前
        check_vector(32'h7f000000);                 // subnormal結果を+0へflush
        check_vector(32'h7f7fffff);                 // 最大有限入力を+0へflush
        check_vector(32'hff7fffff);                 // 最大有限負入力を-0へflush
        check_vector(32'h7f800000);                 // +Inf -> +0
        check_vector(32'hff800000);                 // -Inf -> -0
        check_vector(32'h7fc00001);                 // NaN -> canonical qNaN

        // 32区間の左端、中央、右端付近を複数の結果指数で検査する。
        for (index = 0; index < 32; index = index + 1) begin
            logic [22:0] base_fraction;
            base_fraction = 23'(index << 18);
            check_vector({ 1'b0, 8'd1, base_fraction });
            check_vector({ 1'b0, 8'd127, base_fraction });
            check_vector({ 1'b0, 8'd252, base_fraction });
            check_vector({ 1'b0, 8'd127, base_fraction | 23'h1ffff });
            check_vector({ 1'b0, 8'd127, base_fraction | 23'h3fffe });
            check_vector({ 1'b0, 8'd127, base_fraction | 23'h3ffff });
        end

        for (issue = 0; issue < RANDOM_CYCLES; issue = issue + 1) begin
            logic [31:0] random_bits;
            random_bits = $urandom;
            if (issue[0]) begin
                random_bits[30:23] = 8'($urandom_range(1, 254));
                random_bits[31] = 1'($urandom_range(0, 1));
            end
            check_vector(random_bits);
            if ((issue & 15) == 0)
                check_sign_pair(random_bits[30:0]);
        end

        // 正の非NaN領域を入力bit pattern順に等間隔で選び、逆数が単調非増加か調べる。
        for (issue = 0; issue < MONOTONIC_SAMPLES; issue = issue + 1) begin
            longint unsigned numerator;
            numerator = 64'(issue) * 64'h000000007f800000;
            x = 32'(numerator / (64'(MONOTONIC_SAMPLES) - 64'd1));
            #1;
            if (issue != 0 && ordered_key(result) > ordered_key(previous_result))
                $fatal(1, "単調性違反: x=%h previous=%h actual=%h",
                       x, previous_result, result);
            previous_result = result;
            monotonic_count = monotonic_count + 1;
        end

        $display("PASS: checked=%0d correct=%0d alternative=%0d max_ulp=%0d faithful_normal=%0d monotonic=%0d symmetry=%0d",
                 checked_count, correct_count, faithful_alternative_count,
                 max_ulp, faithful_count, monotonic_count, symmetry_count);
        if (max_ulp != 0)
            $display("WORST: x=%h actual=%h expected=%h",
                     worst_input, worst_actual, worst_expected);
        $finish;
    end
endmodule
