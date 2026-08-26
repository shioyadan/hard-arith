// Copyright 2026 Ryota Shioya
// SPDX-License-Identifier: Apache-2.0

module FP32ExpTB;
    parameter integer RANDOM_CYCLES = 200000;       // 固定seedで生成する乱数入力数
    parameter integer BOUNDARY_STRIDE = 17;         // 引数削減境界を選ぶ間隔
    parameter integer MONOTONIC_SAMPLES = 200000;   // 近似範囲から等間隔に取る単調性標本数

    logic [31:0] x;                                 // DUTへ与えるbinary32 bit pattern
    logic [31:0] result;                            // DUTが返すbinary32 bit pattern
    integer issue;                                  // test loopの位置
    integer random_seed;                            // 再現可能な乱数seed
    integer checked_count;                          // 参照値と比較した入力数
    integer correct_count;                          // correct参照値と一致した入力数
    integer one_ulp_count;                          // correct参照値から1 ULP離れた入力数
    integer faithful_count;                         // faithful上下限の一方と一致した入力数
    integer faithful_ambiguous_count;               // binary128だけでは上下を決めにくい入力数
    integer monotonic_count;                        // 単調性を比較した入力数
    logic [31:0] worst_input;                       // 最大ULPを観測した入力
    logic [31:0] worst_actual;                      // そのときのDUT出力
    logic [31:0] worst_expected;                    // そのときのcorrect参照値
    integer unsigned max_ulp;                       // 最大ULP誤差
    logic [31:0] previous_result;                   // 単調性検査の直前出力
    longint unsigned monotonic_ordinal;             // 近似範囲を数値順に並べた位置

    import "DPI-C" function int unsigned fp32_exp_ref(
        input int unsigned input_bits
    );
    import "DPI-C" function longint unsigned fp32_exp_faithful_bounds(
        input int unsigned input_bits
    );
    import "DPI-C" function int unsigned fp32_exp_faithful_bounds_ambiguous(
        input int unsigned input_bits
    );
    import "DPI-C" function int unsigned fp32_reduction_boundary(
        input int index
    );

    FP32Exp dut (                                   // faithful固定構成を検査する
        .x(x),
        .result(result)
    );

    function automatic logic is_nan(input logic [31:0] value);
        is_nan = value[30:23] == 8'hff && value[22:0] != 0; // NaNのbit patternか判定する
    endfunction

    function automatic logic [31:0] input_from_ordinal(
        input logic [28:0] ordinal
    );
        logic [27:0] rank;                           // 符号を除いた指数・仮数の位置
        begin
            if (!ordinal[28]) begin                 // 前半は負入力を数値の昇順に並べる
                rank = 28'hfffffff - ordinal[27:0]; // 大きい絶対値から小さい絶対値へ進む
                input_from_ordinal = {
                    1'b1, 8'd102 + {3'b0, rank[27:23]}, rank[22:0]
                };
            end else begin                          // 後半は正入力を数値の昇順に並べる
                rank = ordinal[27:0];               // 小さい絶対値から大きい絶対値へ進む
                input_from_ordinal = {
                    1'b0, 8'd102 + {3'b0, rank[27:23]}, rank[22:0]
                };
            end
        end
    endfunction

    task automatic check_vector(input logic [31:0] input_bits);
        logic [31:0] expected;                       // binary128から得たcorrect参照値
        logic [63:0] bounds;                         // faithful上限と下限をまとめた値
        logic [31:0] lower;                          // 厳密値直下のbinary32
        logic [31:0] upper;                          // 厳密値直上のbinary32
        integer unsigned ulp;                        // 非負exp出力どうしのbit距離
        begin
            x = input_bits;                          // DUTへ入力を与える
            #1;                                      // 組合せ回路の評価を進める
            expected = fp32_exp_ref(input_bits);     // binary32参照値を計算する
            if (is_nan(result) && is_nan(expected))  // NaN payloadの差は許容する
                ulp = 0;
            else if (result >= expected)             // 非負出力のbit pattern差をULPとする
                ulp = result - expected;
            else
                ulp = expected - result;

            checked_count = checked_count + 1;       // 比較数を進める
            if (ulp == 0)
                correct_count = correct_count + 1;   // correct一致を数える
            if (ulp == 1)
                one_ulp_count = one_ulp_count + 1;   // 1 ULP差を数える
            if (ulp > max_ulp) begin                 // 最大誤差例を保存する
                max_ulp = ulp;
                worst_input = input_bits;
                worst_actual = result;
                worst_expected = expected;
            end
            if (ulp > 1)                             // 公開RTLの最大1 ULP仕様を検査する
                $fatal(1, "1 ULP超過: x=%h actual=%h expected=%h ulp=%0d",
                       input_bits, result, expected, ulp);

            if (expected != 0 && expected != 32'h7f800000) begin // 非0有限出力だけfaithfulを判定する
                bounds = fp32_exp_faithful_bounds(input_bits); // binary128から上下限を得る
                lower = bounds[31:0];                // faithful下限を取り出す
                upper = bounds[63:32];               // faithful上限を取り出す
                if (fp32_exp_faithful_bounds_ambiguous(input_bits) != 0)
                    faithful_ambiguous_count = faithful_ambiguous_count + 1;
                else if (result == lower || result == upper)
                    faithful_count = faithful_count + 1; // faithfulだった入力を数える
                else
                    $fatal(1, "faithful違反: x=%h actual=%h lower=%h upper=%h",
                           input_bits, result, lower, upper);
            end
        end
    endtask

    initial begin
        x = 0;                                      // DUT入力を初期化する
        random_seed = 32'h00455850;                 // ASCIIのEXPに対応する固定seedを置く
        random_seed = $urandom(random_seed);        // simulatorの乱数系列を固定する
        checked_count = 0;                          // 各counterを初期化する
        correct_count = 0;
        one_ulp_count = 0;
        faithful_count = 0;
        faithful_ambiguous_count = 0;
        monotonic_count = 0;
        max_ulp = 0;
        worst_input = 0;
        worst_actual = 0;
        worst_expected = 0;
        previous_result = 0;
        monotonic_ordinal = 0;

        check_vector(32'h00000000);                 // +0
        check_vector(32'h80000000);                 // -0
        check_vector(32'h00000001);                 // 最小入力subnormal
        check_vector(32'h007fffff);                 // 最大入力subnormal
        check_vector(32'h00800000);                 // 最小入力normal
        check_vector(32'h3f800000);                 // +1
        check_vector(32'hbf800000);                 // -1
        check_vector(32'h42b17218);                 // overflow境界付近
        check_vector(32'hc2cff1b4);                 // underflow境界付近
        check_vector(32'h7f7fffff);                 // 最大有限正入力
        check_vector(32'hff7fffff);                 // 最大有限負入力
        check_vector(32'h7f800000);                 // +Inf
        check_vector(32'hff800000);                 // -Inf
        check_vector(32'h7fc00001);                 // NaN

        for (issue = -9600; issue < 8200; issue = issue + BOUNDARY_STRIDE) begin
            logic [31:0] boundary;                  // 各nの切替境界をbinary32へ丸める
            boundary = fp32_reduction_boundary(issue);
            check_vector(boundary - 1);             // 境界直前を検査する
            check_vector(boundary);                 // 境界自身を検査する
            check_vector(boundary + 1);             // 境界直後を検査する
        end

        for (issue = 0; issue < RANDOM_CYCLES; issue = issue + 1) begin
            logic [31:0] random_bits;               // 固定seedの乱数bit patternを作る
            random_bits = $urandom;
            if (issue[0]) begin                     // 半数は非自明な指数範囲へ集中させる
                random_bits[30:23] = 8'($urandom_range(96, 134));
                random_bits[31] = 1'($urandom_range(0, 1));
            end
            check_vector(random_bits);              // ULPとfaithful性を検査する
        end

        for (issue = 0; issue < MONOTONIC_SAMPLES; issue = issue + 1) begin
            monotonic_ordinal =                     // 全近似範囲から数値順に等間隔で選ぶ
                (64'(issue) * 64'd536870911) / (64'(MONOTONIC_SAMPLES) - 64'd1);
            x = input_from_ordinal(monotonic_ordinal[28:0]); // 選んだbinary32をDUTへ与える
            #1;                                      // 組合せ回路の評価を進める
            if (issue != 0 && result < previous_result)
                $fatal(1, "単調性違反: ordinal=%0d previous=%h actual=%h",
                       monotonic_ordinal, previous_result, result);
            previous_result = result;               // 次の数値順入力との比較へ使う
            monotonic_count = monotonic_count + 1;   // 単調性比較数を進める
        end

        $display("PASS: checked=%0d correct=%0d one_ulp=%0d max_ulp=%0d faithful=%0d ambiguous=%0d monotonic=%0d",
                 checked_count, correct_count, one_ulp_count, max_ulp,
                 faithful_count, faithful_ambiguous_count, monotonic_count);
        if (max_ulp != 0)
            $display("WORST: x=%h actual=%h expected=%h",
                     worst_input, worst_actual, worst_expected);
        $finish;                                     // 全検査の合格を返す
    end
endmodule
