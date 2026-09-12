// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0
// gen_rtl.pyで生成。FP16／BF16の一次方式を実行時に切り替える。
// is_bf16=0: FP16、1: BF16。op=001: exp、010: recip、100: rsqrt。
// 入出力subnormal対応を合成時に選択。有限非zero結果は最大1 RNE step。
// 流れ: 入力分解 → 範囲縮小 → 係数選択 → 共有一次近似 → 正規化・丸め → 特殊値選択。
// Qqは整数値を2^qで割って解釈する固定小数点表記。signedの有無は各wireに明示する。
module FP16BF16ExpRecipRsqrtStudy #(
    parameter integer FORMAT_MODE = 0, // 0: 実行時切替、1: FP16専用、2: BF16専用
    parameter bit SUPPORT_SUBNORMAL = 1'b1
) (
    input wire [15:0] x,
    input wire [2:0] op,
    input wire is_bf16,
    output wire [15:0] result
);
    // 専用設定ではis_bf16を参照せず、形式依存の枝を合成時に定数化する。
    wire use_bf16 = (FORMAT_MODE == 2) || ((FORMAT_MODE == 0) && is_bf16);

    // 1. 入力形式と演算の分解
    // 指数fieldは8 bitへ揃える。input_eはbiasを除いた指数、parityはその偶奇。
    wire select_exp = op == 3'b001;
    wire select_recip = op == 3'b010;
    wire select_rsqrt = op == 3'b100;
    wire valid_op = select_exp | select_recip | select_rsqrt;
    wire [7:0] exponent = use_bf16 ? x[14:7] : {3'd0, x[14:10]};
    wire exponent_zero = ~|exponent;
    wire exponent_all_ones = use_bf16 ? (&exponent) : (&exponent[4:0]);
    wire fraction_zero = use_bf16 ? (~|x[6:0]) : (~|x[9:0]);
    wire signed [8:0] input_e =
        $signed({1'b0, exponent}) - (use_bf16 ? 9'sd127 : 9'sd15);
    // 根系だけ入力subnormalを正規化する。BF16の7 bitも上詰めで10 bitへそろえる。
    wire [9:0] input_fraction = use_bf16 ? {x[6:0], 3'd0} : x[9:0];
    wire input_subnormal = SUPPORT_SUBNORMAL & exponent_zero & !fraction_zero;
    wire input_zero = exponent_zero & (!SUPPORT_SUBNORMAL | fraction_zero);
    wire [3:0] leading_shift =
        input_fraction[9] ? 4'd1 : input_fraction[8] ? 4'd2 :
        input_fraction[7] ? 4'd3 : input_fraction[6] ? 4'd4 :
        input_fraction[5] ? 4'd5 : input_fraction[4] ? 4'd6 :
        input_fraction[3] ? 4'd7 : input_fraction[2] ? 4'd8 :
        input_fraction[1] ? 4'd9 : 4'd10;
    // 左shiftで暗黙の1を落とし、小数部だけを既存の近似格子へ渡す。
    wire [9:0] root_fraction = input_subnormal ? (input_fraction << leading_shift) : input_fraction;
    wire signed [8:0] root_e = input_subnormal ?
        (use_bf16 ? -9'sd126 : -9'sd14) - $signed({5'd0, leading_shift}) : input_e;
    wire parity = root_e[0];

    // 2. expの範囲縮小: z=x*log2(e)、exp(x)=2^floor(z)*2^frac(z)
    // 仮数をQ10へ揃え、Q14のlog2(e)を掛ける。exp_productはQ24。
    // BF16仮数の3 bit左詰めは配線で行い、11×15の定数乗算器を共有する。
    wire [10:0] mantissa = use_bf16 ? {1'b1, x[6:0], 3'd0} : {1'b1, x[9:0]};
    wire [25:0] exp_product = mantissa * 15'd23637;
    // 指数による倍率を反映し、zをFP16ではQ13、BF16ではQ9へ丸める。
    // shift量はFP16: 26-指数field、BF16: 142-指数field。減算せず直接decodeする。
    // exp_grs={保持する19 bit, guard, sticky}。各枝では配線だけを選択する。
    wire [20:0] exp_grs;
    assign exp_grs =
        (use_bf16 ? (x[14:7] == 8'd116) : (x[14:10] == 5'd0)) ?
            {{19'd0}, exp_product[25], 1'b1} :
        (use_bf16 ? (x[14:7] == 8'd117) : (x[14:10] == 5'd1)) ?
            {{18'd0, exp_product[25:25]}, exp_product[24], 1'b1} :
        (use_bf16 ? (x[14:7] == 8'd118) : (x[14:10] == 5'd2)) ?
            {{17'd0, exp_product[25:24]}, exp_product[23], 1'b1} :
        (use_bf16 ? (x[14:7] == 8'd119) : (x[14:10] == 5'd3)) ?
            {{16'd0, exp_product[25:23]}, exp_product[22], 1'b1} :
        (use_bf16 ? (x[14:7] == 8'd120) : (x[14:10] == 5'd4)) ?
            {{15'd0, exp_product[25:22]}, exp_product[21], 1'b1} :
        (use_bf16 ? (x[14:7] == 8'd121) : (x[14:10] == 5'd5)) ?
            {{14'd0, exp_product[25:21]}, exp_product[20], 1'b1} :
        (use_bf16 ? (x[14:7] == 8'd122) : (x[14:10] == 5'd6)) ?
            {{13'd0, exp_product[25:20]}, exp_product[19], 1'b1} :
        (use_bf16 ? (x[14:7] == 8'd123) : (x[14:10] == 5'd7)) ?
            {{12'd0, exp_product[25:19]}, exp_product[18], 1'b1} :
        (use_bf16 ? (x[14:7] == 8'd124) : (x[14:10] == 5'd8)) ?
            {{11'd0, exp_product[25:18]}, exp_product[17], 1'b1} :
        (use_bf16 ? (x[14:7] == 8'd125) : (x[14:10] == 5'd9)) ?
            {{10'd0, exp_product[25:17]}, exp_product[16], 1'b1} :
        (use_bf16 ? (x[14:7] == 8'd126) : (x[14:10] == 5'd10)) ?
            {{9'd0, exp_product[25:16]}, exp_product[15], 1'b1} :
        (use_bf16 ? (x[14:7] == 8'd127) : (x[14:10] == 5'd11)) ?
            {{8'd0, exp_product[25:15]}, exp_product[14], 1'b1} :
        (use_bf16 ? (x[14:7] == 8'd128) : (x[14:10] == 5'd12)) ?
            {{7'd0, exp_product[25:14]}, exp_product[13], 1'b1} :
        (use_bf16 ? (x[14:7] == 8'd129) : (x[14:10] == 5'd13)) ?
            {{6'd0, exp_product[25:13]}, exp_product[12], 1'b1} :
        (use_bf16 ? (x[14:7] == 8'd130) : (x[14:10] == 5'd14)) ?
            {{5'd0, exp_product[25:12]}, exp_product[11], 1'b1} :
        (use_bf16 ? (x[14:7] == 8'd131) : (x[14:10] == 5'd15)) ?
            {{4'd0, exp_product[25:11]}, exp_product[10], (|mantissa[9:0])} :
        (use_bf16 ? (x[14:7] == 8'd132) : (x[14:10] == 5'd16)) ?
            {{3'd0, exp_product[25:10]}, exp_product[9], (|mantissa[8:0])} :
        (use_bf16 ? (x[14:7] == 8'd133) : (x[14:10] == 5'd17)) ?
            {{2'd0, exp_product[25:9]}, exp_product[8], (|mantissa[7:0])} :
        (use_bf16 ? (x[14:7] == 8'd134) : (x[14:10] == 5'd18)) ?
            {{1'd0, exp_product[25:8]}, exp_product[7], (|mantissa[6:0])} :
        (use_bf16 ? (x[14:7] == 8'd135) : (x[14:10] == 5'd19)) ?
            {exp_product[25:7], exp_product[6], (|mantissa[5:0])} :
        21'd0;
    // RNEの繰上げ条件はguard && (sticky || 保持部LSB)。tieは偶数側へ丸める。
    wire [18:0] exp_magnitude =
        exp_grs[20:2] + {18'd0, (exp_grs[1] & (exp_grs[0] | exp_grs[2]))};
    wire signed [19:0] exp_z =
        x[15] ? -$signed({1'b0, exp_magnitude}) : $signed({1'b0, exp_magnitude});

    // 近似に使うtの下位bitは、根系ではm-1、expではfrac(z)を表す。
    // 有効な小数部はFP16: t[12:0] (Q13)、BF16: t[8:0] (Q9)。
    // 負のexp_zも下位bitがfrac(z)、上位bitがfloor(z)を表す。
    wire [12:0] root_t = use_bf16 ? {4'd0, root_fraction[9:3], 2'd0} : {root_fraction, 3'd0};
    wire [12:0] t = select_exp ? exp_z[12:0] : root_t;

    // 3. 区間中心からの残差dと係数c0・c1を選ぶ
    // 区間内の下位bitのMSB反転は「下位bit値-区間幅/2」のsigned表現になる。
    // rsqrtの表はparity=0が前半、parity=1が後半。

    // FP16: dはQ11、c0はQ13、c1はQ7。
    // exp: 16区間。
    wire [3:0] fp16_exp_index = t[12:9];
    wire signed [6:0] fp16_exp_d = {~t[8], t[7:2]};
    localparam logic [13:0] FP16_EXP_C0 [0:15] = '{
        14'd8372, 14'd8743, 14'd9130, 14'd9534, // index 0..3
        14'd9956, 14'd10397, 14'd10858, 14'd11338, // index 4..7
        14'd11840, 14'd12365, 14'd12912, 14'd13484, // index 8..11
        14'd14081, 14'd14704, 14'd15355, 14'd16035 // index 12..15
    };
    wire [13:0] fp16_exp_c0 = FP16_EXP_C0[fp16_exp_index];
    localparam logic signed [8:0] FP16_EXP_C1 [0:15] = '{
        9'sd91, 9'sd95, 9'sd99, 9'sd103, // index 0..3
        9'sd108, 9'sd113, 9'sd118, 9'sd123, // index 4..7
        9'sd128, 9'sd134, 9'sd140, 9'sd146, // index 8..11
        9'sd152, 9'sd159, 9'sd166, 9'sd174 // index 12..15
    };
    wire signed [8:0] fp16_exp_c1 = FP16_EXP_C1[fp16_exp_index];

    // recip: 16区間。
    wire [3:0] fp16_recip_index = t[12:9];
    wire signed [6:0] fp16_recip_d = {~t[8], t[7:2]};
    localparam logic [12:0] FP16_RECIP_C0 [0:15] = '{
        13'd7947, 13'd7493, 13'd7088, 13'd6724, // index 0..3
        13'd6396, 13'd6098, 13'd5827, 13'd5579, // index 4..7
        13'd5351, 13'd5141, 13'd4947, 13'd4767, // index 8..11
        13'd4600, 13'd4444, 13'd4298, 13'd4162 // index 12..15
    };
    wire [12:0] fp16_recip_c0 = FP16_RECIP_C0[fp16_recip_index];
    localparam logic signed [7:0] FP16_RECIP_C1 [0:15] = '{
        -8'sd120, -8'sd107, -8'sd96, -8'sd86, // index 0..3
        -8'sd78, -8'sd71, -8'sd65, -8'sd59, // index 4..7
        -8'sd55, -8'sd50, -8'sd47, -8'sd43, // index 8..11
        -8'sd40, -8'sd38, -8'sd35, -8'sd33 // index 12..15
    };
    wire signed [7:0] fp16_recip_c1 = FP16_RECIP_C1[fp16_recip_index];

    // rsqrt: 16区間×指数偶奇2通り。
    wire [4:0] fp16_rsqrt_index = {parity, t[12:9]};
    wire signed [6:0] fp16_rsqrt_d = {~t[8], t[7:2]};
    localparam logic [12:0] FP16_RSQRT_C0 [0:31] = '{
        13'd8068, 13'd7834, 13'd7619, 13'd7421, // index 0..3
        13'd7238, 13'd7068, 13'd6909, 13'd6760, // index 4..7
        13'd6621, 13'd6489, 13'd6366, 13'd6249, // index 8..11
        13'd6138, 13'd6033, 13'd5934, 13'd5839, // index 12..15
        13'd5705, 13'd5540, 13'd5388, 13'd5248, // index 16..19
        13'd5118, 13'd4998, 13'd4885, 13'd4780, // index 20..23
        13'd4682, 13'd4589, 13'd4501, 13'd4419, // index 24..27
        13'd4340, 13'd4266, 13'd4196, 13'd4129 // index 28..31
    };
    wire [12:0] fp16_rsqrt_c0 = FP16_RSQRT_C0[fp16_rsqrt_index];
    localparam logic signed [6:0] FP16_RSQRT_C1 [0:31] = '{
        -7'sd61, -7'sd56, -7'sd51, -7'sd48, // index 0..3
        -7'sd44, -7'sd41, -7'sd38, -7'sd36, // index 4..7
        -7'sd34, -7'sd32, -7'sd30, -7'sd28, // index 8..11
        -7'sd27, -7'sd26, -7'sd24, -7'sd23, // index 12..15
        -7'sd43, -7'sd40, -7'sd36, -7'sd34, // index 16..19
        -7'sd31, -7'sd29, -7'sd27, -7'sd25, // index 20..23
        -7'sd24, -7'sd22, -7'sd21, -7'sd20, // index 24..27
        -7'sd19, -7'sd18, -7'sd17, -7'sd16 // index 28..31
    };
    wire signed [6:0] fp16_rsqrt_c1 = FP16_RSQRT_C1[fp16_rsqrt_index];

    // FP16内で演算を選択し、共有カーネルの幅へ明示的に拡張する。
    wire signed [6:0] fp16_d =
        select_exp   ? $signed(fp16_exp_d) :
        select_recip ? $signed(fp16_recip_d) :
                       $signed(fp16_rsqrt_d);
    wire [13:0] fp16_c0 =
        select_exp   ? fp16_exp_c0 :
        select_recip ? {{1{1'b0}}, fp16_recip_c0} :
                       {{1{1'b0}}, fp16_rsqrt_c0};
    wire signed [8:0] fp16_c1 =
        select_exp   ? $signed(fp16_exp_c1) :
        select_recip ? $signed({{1{fp16_recip_c1[7]}}, fp16_recip_c1}) :
                       $signed({{2{fp16_rsqrt_c1[6]}}, fp16_rsqrt_c1});

    // BF16: dはQ8、c0はQ9、c1はQ5。
    // exp: 4区間。
    wire [1:0] bf16_exp_index = t[8:7];
    wire signed [5:0] bf16_exp_d = {~t[6], t[5:1]};
    localparam logic [9:0] BF16_EXP_C0 [0:3] = '{
        10'd559, 10'd665, 10'd791, 10'd941 // index 0..3
    };
    wire [9:0] bf16_exp_c0 = BF16_EXP_C0[bf16_exp_index];
    localparam logic signed [6:0] BF16_EXP_C1 [0:3] = '{
        7'sd24, 7'sd29, 7'sd34, 7'sd41 // index 0..3
    };
    wire signed [6:0] bf16_exp_c1 = BF16_EXP_C1[bf16_exp_index];

    // recip: 8区間。
    wire [2:0] bf16_recip_index = t[8:6];
    wire signed [4:0] bf16_recip_d = {~t[5], t[4:1]};
    localparam logic [8:0] BF16_RECIP_C0 [0:7] = '{
        9'd483, 9'd432, 9'd391, 9'd357, // index 0..3
        9'd328, 9'd304, 9'd283, 9'd264 // index 4..7
    };
    wire [8:0] bf16_recip_c0 = BF16_RECIP_C0[bf16_recip_index];
    localparam logic signed [5:0] BF16_RECIP_C1 [0:7] = '{
        -6'sd28, -6'sd23, -6'sd19, -6'sd16, // index 0..3
        -6'sd13, -6'sd11, -6'sd10, -6'sd9 // index 4..7
    };
    wire signed [5:0] bf16_recip_c1 = BF16_RECIP_C1[bf16_recip_index];

    // rsqrt: 4区間×指数偶奇2通り。
    wire [2:0] bf16_rsqrt_index = {parity, t[8:7]};
    wire signed [5:0] bf16_rsqrt_d = {~t[6], t[5:1]};
    localparam logic [8:0] BF16_RSQRT_C0 [0:7] = '{
        9'd484, 9'd437, 9'd402, 9'd374, // index 0..3
        9'd342, 9'd309, 9'd284, 9'd265 // index 4..7
    };
    wire [8:0] bf16_rsqrt_c0 = BF16_RSQRT_C0[bf16_rsqrt_index];
    localparam logic signed [4:0] BF16_RSQRT_C1 [0:7] = '{
        -5'sd13, -5'sd10, -5'sd8, -5'sd6, // index 0..3
        -5'sd10, -5'sd7, -5'sd5, -5'sd4 // index 4..7
    };
    wire signed [4:0] bf16_rsqrt_c1 = BF16_RSQRT_C1[bf16_rsqrt_index];

    // BF16内で演算を選択し、共有カーネルの幅へ明示的に拡張する。
    wire signed [6:0] bf16_d =
        select_exp   ? $signed({{1{bf16_exp_d[5]}}, bf16_exp_d}) :
        select_recip ? $signed({{2{bf16_recip_d[4]}}, bf16_recip_d}) :
                       $signed({{1{bf16_rsqrt_d[5]}}, bf16_rsqrt_d});
    wire [13:0] bf16_c0 =
        select_exp   ? {{4{1'b0}}, bf16_exp_c0} :
        select_recip ? {{5{1'b0}}, bf16_recip_c0} :
                       {{5{1'b0}}, bf16_rsqrt_c0};
    wire signed [8:0] bf16_c1 =
        select_exp   ? $signed({{2{bf16_exp_c1[6]}}, bf16_exp_c1}) :
        select_recip ? $signed({{3{bf16_recip_c1[5]}}, bf16_recip_c1}) :
                       $signed({{4{bf16_rsqrt_c1[4]}}, bf16_rsqrt_c1});

    // 4. 一つの7×9乗算器で、一次近似y=c0+floor(d*c1)を計算する
    // 小数点位置は形式ごとに維持し、符号拡張だけで共有乗算器へ渡す。
    wire signed [6:0] d = use_bf16 ? bf16_d : fp16_d;
    wire [13:0] c0 = use_bf16 ? bf16_c0 : fp16_c0;
    wire signed [8:0] c1 = use_bf16 ? bf16_c1 : fp16_c1;
    wire signed [15:0] product = d * c1;
    // 積はFP16: Q18、BF16: Q13。5／4 bit右へ切り下げ、c0と同じQ13／Q9に戻す。
    // signedの上位sliceは負方向へのfloor。最終出力ではRNEする。
    wire signed [15:0] correction = use_bf16 ? $signed({{4{product[15]}}, product[15:4]})
                                          : $signed({{5{product[15]}}, product[15:5]});
    wire signed [15:0] polynomial = $signed({2'd0, c0}) + correction;
    // recip(m=1)、rsqrt(m=1かつ偶数指数)は近似せず、厳密な1を選択する。
    wire exact_root = !select_exp & (~|root_fraction) & (select_recip | !parity);
    wire [13:0] y = exact_root ? (use_bf16 ? 14'd512 : 14'd8192) : polynomial[13:0];

    // 5. 正規化、指数復元、出力形式へのRNE
    // 根系の非厳密点は[0.5,1)。expの1未満の値も、出力RNEでは必ず1へ丸まる。
    // 全入力の丸め・FTZ照合により、近似結果を待たずに正規化位置を決められる。
    wire signed [2:0] normalization = (select_exp | exact_root) ? 3'sd0 : -3'sd1;
    wire signed [8:0] exp_scale = use_bf16 ? $signed(exp_z[17:9]) : $signed({{2{exp_z[19]}}, exp_z[19:13]});
    // exp: floor(z)、recip: -e、rsqrt: -floor(e/2)を復元する。
    wire signed [8:0] scale = select_exp ? exp_scale : select_recip ? -root_e : -(root_e >>> 1);
    wire signed [9:0] biased_before = $signed({scale[8], scale}) + (use_bf16 ? 10'sd127 : 10'sd15)
                                   + $signed({{7{normalization[2]}}, normalization});
    // underflow時は最小normalの仮数位置へそろえる。FTZでも境界のRNEは保持する。
    wire near_underflow = SUPPORT_SUBNORMAL ? (biased_before <= 10'sd0) : (biased_before == 10'sd0);
    wire signed [2:0] pack_adjust = normalization + $signed({2'd0, near_underflow});
    wire [12:0] fp16_pack_grs = (pack_adjust == -3'sd1) ? {y[12:2], y[1], (|y[0:0])} :
        (pack_adjust == 3'sd0) ? {y[13:3], y[2], (|y[1:0])} :
        {{1'd0, y[13:4]}, y[3], (|y[2:0])};
    wire [9:0] bf16_pack_grs = (pack_adjust == -3'sd1) ? {y[8:1], y[0], 1'b0} :
        (pack_adjust == 3'sd0) ? {y[9:2], y[1], (|y[0:0])} :
        {{1'd0, y[9:3]}, y[2], (|y[1:0])};
    // 追加の右shiftは丸め前に行い、捨てるbitをstickyへ集約する。
    // 13 bit以上のshiftは同じzeroへ丸まるため、制御幅を4 bitへ制限する。
    wire [3:0] denormal_shift = (SUPPORT_SUBNORMAL && biased_before < 10'sd0) ?
        ((biased_before < -10'sd12) ? 4'd13 : (4'd0 - biased_before[3:0])) : 4'd0;
    wire [12:0] unshifted_grs = use_bf16 ? {3'd0, bf16_pack_grs} : fp16_pack_grs;
    wire [12:0] denormal_grs_1 = denormal_shift[0] ?
        {1'd0, unshifted_grs[12:2], (|unshifted_grs[1:0])} : unshifted_grs;
    wire [12:0] denormal_grs_2 = denormal_shift[1] ?
        {2'd0, denormal_grs_1[12:3], (|denormal_grs_1[2:0])} : denormal_grs_1;
    wire [12:0] denormal_grs_4 = denormal_shift[2] ?
        {4'd0, denormal_grs_2[12:5], (|denormal_grs_2[4:0])} : denormal_grs_2;
    wire [12:0] pack_grs = denormal_shift[3] ?
        {8'd0, denormal_grs_4[12:9], (|denormal_grs_4[8:0])} : denormal_grs_4;
    // pack_grs[12:2]が保持部、[1]がguard、[0]がsticky。最終RNEは一度だけ。
    // 現行係数・残差幅では、RNE後も仮数が2に達しないことを全入力で確認する。
    // min normalへの繰上げは隠れbitへ反映し、normalの指数carryとは区別する。
    wire [10:0] packed_m = pack_grs[12:2] + {10'd0, (pack_grs[1] & (pack_grs[0] | pack_grs[2]))};
    wire signed [9:0] packed_e = near_underflow ? 10'sd1 : biased_before;
    wire [9:0] packed_fraction = use_bf16 ? {3'd0, packed_m[6:0]} : packed_m[9:0];
    // 正のInf: BF16=0x7f80、FP16=0x7c00。qNaN: BF16=0x7fc0、FP16=0x7e00。
    wire [14:0] inf = use_bf16 ? 15'd32640 : 15'd31744;
    wire [15:0] nan = use_bf16 ? 16'd32704 : 16'd32256;
    wire [14:0] normal_payload = use_bf16 ? {packed_e[7:0], packed_fraction[6:0]} : {packed_e[4:0], packed_fraction};
    wire tiny_result = packed_m < (use_bf16 ? 11'd128 : 11'd1024);
    wire [14:0] finite_payload = SUPPORT_SUBNORMAL && near_underflow && tiny_result ?
                                {5'd0, packed_fraction} :
                                (biased_before < 10'sd0 || tiny_result) ? 15'd0
                              : (packed_e >= (use_bf16 ? 10'sd255 : 10'sd31)) ? inf : normal_payload;

    // 6. 特殊値と無効opの選択（近似結果より優先する）
    // FP16の|x|>=32、BF16の|x|>=128はInf／zeroとなり、近似経路を使わない。
    wire is_nan = exponent_all_ones & !fraction_zero;
    wire negative_rsqrt = select_rsqrt & x[15] & !input_zero;
    wire exp_large = use_bf16 ? (input_e >= 9'sd7) : (input_e >= 9'sd5);
    // exp(±0)=1: BF16=0x3f80、FP16=0x3c00。
    wire [15:0] exp_result = exponent_zero ? (use_bf16 ? 16'd16256 : 16'd15360)
                           : exp_large ? (x[15] ? 16'd0 : {1'b0, inf}) : {1'b0, finite_payload};
    wire [15:0] root_result = input_zero ? {x[15], inf}
                            : exponent_all_ones ? {(select_recip & x[15]), 15'd0}
                            : {(select_recip & x[15]), finite_payload};
    assign result = (!valid_op | is_nan | negative_rsqrt) ? nan : select_exp ? exp_result : root_result;
endmodule
