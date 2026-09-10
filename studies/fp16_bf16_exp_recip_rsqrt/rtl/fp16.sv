// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0
// gen_rtl.pyで生成。FP16／BF16の一次方式を実行時に切り替える。
// is_bf16=0: FP16、1: BF16。op=001: exp、010: recip、100: rsqrt。
// 入出力FTZ、normal結果は最大1 RNE step。特殊値の仕様はREADME.mdを参照。
// 流れ: 入力分解 → 範囲縮小 → 係数選択 → 共有一次近似 → 正規化・丸め → 特殊値選択。
// Qqは整数値を2^qで割って解釈する固定小数点表記。signedの有無は各wireに明示する。
module FP16BF16ExpRecipRsqrtStudy (
    input wire [15:0] x,
    input wire [2:0] op,
    input wire is_bf16,
    output wire [15:0] result
);
    // 1. 入力形式と演算の分解
    // 指数fieldは8 bitへ揃える。input_eはbiasを除いた指数、parityはその偶奇。
    wire select_exp = op == 3'b001;
    wire select_recip = op == 3'b010;
    wire select_rsqrt = op == 3'b100;
    wire valid_op = select_exp | select_recip | select_rsqrt;
    wire [7:0] exponent = is_bf16 ? x[14:7] : {3'd0, x[14:10]};
    wire exponent_zero = ~|exponent;
    wire exponent_all_ones = is_bf16 ? (&exponent) : (&exponent[4:0]);
    wire fraction_zero = is_bf16 ? (~|x[6:0]) : (~|x[9:0]);
    wire signed [8:0] input_e =
        $signed({1'b0, exponent}) - (is_bf16 ? 9'sd127 : 9'sd15);
    wire parity = input_e[0];

    // 2. expの範囲縮小: z=x*log2(e)、exp(x)=2^floor(z)*2^frac(z)
    // 仮数をQ10へ揃え、Q14のlog2(e)を掛ける。exp_productはQ24。
    // BF16仮数の3 bit左詰めは配線で行い、11×15の定数乗算器を共有する。
    wire [10:0] mantissa = is_bf16 ? {1'b1, x[6:0], 3'd0} : {1'b1, x[9:0]};
    wire [25:0] exp_product = mantissa * 15'd23637;
    // 指数による倍率を反映し、zをFP16ではQ13、BF16ではQ9へ丸める。
    wire signed [9:0] exp_shift =
        (is_bf16 ? 10'sd15 : 10'sd11) - $signed({input_e[8], input_e});
    // exp_grs={保持する21 bit, guard, sticky}。各枝では配線だけを選択する。
    wire [22:0] exp_grs;
    assign exp_grs =
        (exp_shift == 10'sd26) ? {{21'd0}, exp_product[25], (|exp_product[24:0])} :
        (exp_shift == 10'sd25) ? {{20'd0, exp_product[25:25]}, exp_product[24], (|exp_product[23:0])} :
        (exp_shift == 10'sd24) ? {{19'd0, exp_product[25:24]}, exp_product[23], (|exp_product[22:0])} :
        (exp_shift == 10'sd23) ? {{18'd0, exp_product[25:23]}, exp_product[22], (|exp_product[21:0])} :
        (exp_shift == 10'sd22) ? {{17'd0, exp_product[25:22]}, exp_product[21], (|exp_product[20:0])} :
        (exp_shift == 10'sd21) ? {{16'd0, exp_product[25:21]}, exp_product[20], (|exp_product[19:0])} :
        (exp_shift == 10'sd20) ? {{15'd0, exp_product[25:20]}, exp_product[19], (|exp_product[18:0])} :
        (exp_shift == 10'sd19) ? {{14'd0, exp_product[25:19]}, exp_product[18], (|exp_product[17:0])} :
        (exp_shift == 10'sd18) ? {{13'd0, exp_product[25:18]}, exp_product[17], (|exp_product[16:0])} :
        (exp_shift == 10'sd17) ? {{12'd0, exp_product[25:17]}, exp_product[16], (|exp_product[15:0])} :
        (exp_shift == 10'sd16) ? {{11'd0, exp_product[25:16]}, exp_product[15], (|exp_product[14:0])} :
        (exp_shift == 10'sd15) ? {{10'd0, exp_product[25:15]}, exp_product[14], (|exp_product[13:0])} :
        (exp_shift == 10'sd14) ? {{9'd0, exp_product[25:14]}, exp_product[13], (|exp_product[12:0])} :
        (exp_shift == 10'sd13) ? {{8'd0, exp_product[25:13]}, exp_product[12], (|exp_product[11:0])} :
        (exp_shift == 10'sd12) ? {{7'd0, exp_product[25:12]}, exp_product[11], (|exp_product[10:0])} :
        (exp_shift == 10'sd11) ? {{6'd0, exp_product[25:11]}, exp_product[10], (|exp_product[9:0])} :
        (exp_shift == 10'sd10) ? {{5'd0, exp_product[25:10]}, exp_product[9], (|exp_product[8:0])} :
        (exp_shift == 10'sd9) ? {{4'd0, exp_product[25:9]}, exp_product[8], (|exp_product[7:0])} :
        (exp_shift == 10'sd8) ? {{3'd0, exp_product[25:8]}, exp_product[7], (|exp_product[6:0])} :
        (exp_shift == 10'sd7) ? {{2'd0, exp_product[25:7]}, exp_product[6], (|exp_product[5:0])} :
        (exp_shift == 10'sd6) ? {{1'd0, exp_product[25:6]}, exp_product[5], (|exp_product[4:0])} :
        (exp_shift == 10'sd5) ? {exp_product[25:5], exp_product[4], (|exp_product[3:0])} :
        23'd0;
    // RNEの繰上げ条件はguard && (sticky || 保持部LSB)。tieは偶数側へ丸める。
    wire [20:0] exp_magnitude =
        exp_grs[22:2] + {20'd0, (exp_grs[1] & (exp_grs[0] | exp_grs[2]))};
    wire signed [21:0] exp_z =
        x[15] ? -$signed({1'b0, exp_magnitude}) : $signed({1'b0, exp_magnitude});

    // 近似に使うtの下位bitは、根系ではm-1、expではfrac(z)を表す。
    // 有効な小数部はFP16: t[12:0] (Q13)、BF16: t[8:0] (Q9)。
    // 負のexp_zも下位bitがfrac(z)、上位bitがfloor(z)を表す。
    wire [12:0] root_t = is_bf16 ? {4'd0, x[6:0], 2'd0} : {x[9:0], 3'd0};
    wire [12:0] t = select_exp ? exp_z[12:0] : root_t;

    // 3. 区間中心からの残差dと係数c0・c1を選ぶ
    // 区間内の下位bitのMSB反転は「下位bit値-区間幅/2」のsigned表現になる。
    // rsqrtの表はparity=0が前半、parity=1が後半。

    // FP16: d・c0はQ13、c1はQ9。
    // exp: 16区間。
    wire [3:0] fp16_exp_index = t[12:9];
    wire signed [8:0] fp16_exp_d = {~t[8], t[7:0]};
    localparam logic [13:0] FP16_EXP_C0 [0:15] = '{
        14'd8372, 14'd8743, 14'd9130, 14'd9534, // index 0..3
        14'd9956, 14'd10397, 14'd10858, 14'd11338, // index 4..7
        14'd11840, 14'd12365, 14'd12912, 14'd13484, // index 8..11
        14'd14081, 14'd14704, 14'd15355, 14'd16035 // index 12..15
    };
    wire [13:0] fp16_exp_c0 = FP16_EXP_C0[fp16_exp_index];
    localparam logic signed [10:0] FP16_EXP_C1 [0:15] = '{
        11'sd363, 11'sd379, 11'sd396, 11'sd413, // index 0..3
        11'sd431, 11'sd450, 11'sd470, 11'sd491, // index 4..7
        11'sd513, 11'sd536, 11'sd559, 11'sd584, // index 8..11
        11'sd610, 11'sd637, 11'sd665, 11'sd695 // index 12..15
    };
    wire signed [10:0] fp16_exp_c1 = FP16_EXP_C1[fp16_exp_index];

    // recip: 16区間。
    wire [3:0] fp16_recip_index = t[12:9];
    wire signed [8:0] fp16_recip_d = {~t[8], t[7:0]};
    localparam logic [12:0] FP16_RECIP_C0 [0:15] = '{
        13'd7947, 13'd7493, 13'd7088, 13'd6724, // index 0..3
        13'd6396, 13'd6098, 13'd5827, 13'd5579, // index 4..7
        13'd5351, 13'd5141, 13'd4947, 13'd4767, // index 8..11
        13'd4600, 13'd4444, 13'd4298, 13'd4162 // index 12..15
    };
    wire [12:0] fp16_recip_c0 = FP16_RECIP_C0[fp16_recip_index];
    localparam logic signed [9:0] FP16_RECIP_C1 [0:15] = '{
        -10'sd482, -10'sd428, -10'sd383, -10'sd345, // index 0..3
        -10'sd312, -10'sd284, -10'sd259, -10'sd237, // index 4..7
        -10'sd218, -10'sd202, -10'sd187, -10'sd173, // index 8..11
        -10'sd161, -10'sd151, -10'sd141, -10'sd132 // index 12..15
    };
    wire signed [9:0] fp16_recip_c1 = FP16_RECIP_C1[fp16_recip_index];

    // rsqrt: 16区間×指数偶奇2通り。
    wire [4:0] fp16_rsqrt_index = {parity, t[12:9]};
    wire signed [8:0] fp16_rsqrt_d = {~t[8], t[7:0]};
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
    localparam logic signed [8:0] FP16_RSQRT_C1 [0:31] = '{
        -9'sd245, -9'sd224, -9'sd206, -9'sd190, // index 0..3
        -9'sd177, -9'sd164, -9'sd154, -9'sd144, // index 4..7
        -9'sd135, -9'sd127, -9'sd120, -9'sd114, // index 8..11
        -9'sd108, -9'sd102, -9'sd97, -9'sd93, // index 12..15
        -9'sd173, -9'sd158, -9'sd146, -9'sd135, // index 16..19
        -9'sd125, -9'sd116, -9'sd109, -9'sd102, // index 20..23
        -9'sd96, -9'sd90, -9'sd85, -9'sd80, // index 24..27
        -9'sd76, -9'sd72, -9'sd69, -9'sd66 // index 28..31
    };
    wire signed [8:0] fp16_rsqrt_c1 = FP16_RSQRT_C1[fp16_rsqrt_index];

    // FP16内で演算を選択し、共有カーネルの幅へ明示的に拡張する。
    wire signed [8:0] fp16_d =
        select_exp   ? $signed(fp16_exp_d) :
        select_recip ? $signed(fp16_recip_d) :
                       $signed(fp16_rsqrt_d);
    wire [13:0] fp16_c0 =
        select_exp   ? fp16_exp_c0 :
        select_recip ? {{1{1'b0}}, fp16_recip_c0} :
                       {{1{1'b0}}, fp16_rsqrt_c0};
    wire signed [10:0] fp16_c1 =
        select_exp   ? $signed(fp16_exp_c1) :
        select_recip ? $signed({{1{fp16_recip_c1[9]}}, fp16_recip_c1}) :
                       $signed({{2{fp16_rsqrt_c1[8]}}, fp16_rsqrt_c1});

    // BF16: d・c0はQ9、c1はQ5。
    // exp: 4区間。
    wire [1:0] bf16_exp_index = t[8:7];
    wire signed [6:0] bf16_exp_d = {~t[6], t[5:0]};
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
    wire signed [5:0] bf16_recip_d = {~t[5], t[4:0]};
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
    wire signed [6:0] bf16_rsqrt_d = {~t[6], t[5:0]};
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
    wire signed [8:0] bf16_d =
        select_exp   ? $signed({{2{bf16_exp_d[6]}}, bf16_exp_d}) :
        select_recip ? $signed({{3{bf16_recip_d[5]}}, bf16_recip_d}) :
                       $signed({{2{bf16_rsqrt_d[6]}}, bf16_rsqrt_d});
    wire [13:0] bf16_c0 =
        select_exp   ? {{4{1'b0}}, bf16_exp_c0} :
        select_recip ? {{5{1'b0}}, bf16_recip_c0} :
                       {{5{1'b0}}, bf16_rsqrt_c0};
    wire signed [10:0] bf16_c1 =
        select_exp   ? $signed({{4{bf16_exp_c1[6]}}, bf16_exp_c1}) :
        select_recip ? $signed({{5{bf16_recip_c1[5]}}, bf16_recip_c1}) :
                       $signed({{6{bf16_rsqrt_c1[4]}}, bf16_rsqrt_c1});

    // 4. 一つの9×11乗算器で、一次近似y=c0+RNE(d*c1)を計算する
    // 小数点位置は形式ごとに維持し、符号拡張だけで共有乗算器へ渡す。
    wire signed [8:0] d = is_bf16 ? bf16_d : fp16_d;
    wire [13:0] c0 = is_bf16 ? bf16_c0 : fp16_c0;
    wire signed [10:0] c1 = is_bf16 ? bf16_c1 : fp16_c1;
    wire signed [19:0] product = d * c1;
    // 積はFP16: Q22、BF16: Q14。9／5 bit右へRNEしてc0と同じQ13／Q9に戻す。
    // signedの上位sliceは負の積を負方向へ切り下げる。そこへRNEの1 bitを加える。
    wire product_round = is_bf16 ? (product[4] & ((|product[3:0]) | product[5]))
                                : (product[8] & ((|product[7:0]) | product[9]));
    wire signed [15:0] product_high = is_bf16 ? $signed({product[19], product[19:5]})
                                            : $signed({{5{product[19]}}, product[19:9]});
    wire signed [15:0] correction = product_high + $signed({15'd0, product_round});
    wire signed [15:0] polynomial = $signed({2'd0, c0}) + correction;
    // recip(m=1)、rsqrt(m=1かつ偶数指数)は近似せず、厳密な1を選択する。
    wire exact_root = !select_exp & fraction_zero & (select_recip | !parity);
    wire [14:0] y = exact_root ? (is_bf16 ? 15'd512 : 15'd8192) : polynomial[14:0];

    // 5. 正規化、指数復元、出力形式へのRNE
    // yはQ13／Q9。到達するbinadeは[0.5,1)、[1,2)、[2,4)の三つだけ。
    wire y_ge_two = is_bf16 ? y[10] : y[14];
    wire y_ge_one = is_bf16 ? y[9] : y[13];
    wire signed [2:0] normalization = y_ge_two ? 3'sd1 : y_ge_one ? 3'sd0 : -3'sd1;
    wire signed [8:0] exp_scale = is_bf16 ? $signed(exp_z[17:9]) : $signed(exp_z[21:13]);
    // exp: floor(z)、recip: -e、rsqrt: -floor(e/2)を復元する。
    wire signed [8:0] scale = select_exp ? exp_scale : select_recip ? -input_e : -(input_e >>> 1);
    wire signed [9:0] biased_before = $signed({scale[8], scale}) + (is_bf16 ? 10'sd127 : 10'sd15)
                                   + $signed({{7{normalization[2]}}, normalization});
    // min normal直下も一度丸め、min normalへ繰り上がらなかった出力だけFTZにする。
    wire near_underflow = biased_before == 10'sd0;
    wire signed [2:0] pack_adjust = normalization + $signed({2'd0, near_underflow});
    wire [12:0] fp16_pack_grs = (pack_adjust == -3'sd1) ? {y[12:2], y[1], (|y[0:0])} :
        (pack_adjust == 3'sd0) ? {y[13:3], y[2], (|y[1:0])} :
        (pack_adjust == 3'sd1) ? {y[14:4], y[3], (|y[2:0])} :
        {{1'd0, y[14:5]}, y[4], (|y[3:0])};
    wire [9:0] bf16_pack_grs = (pack_adjust == -3'sd1) ? {y[8:1], y[0], 1'b0} :
        (pack_adjust == 3'sd0) ? {y[9:2], y[1], (|y[0:0])} :
        (pack_adjust == 3'sd1) ? {y[10:3], y[2], (|y[1:0])} :
        {{1'd0, y[10:4]}, y[3], (|y[2:0])};
    // pack_grs[12:2]が保持部、[1]がguard、[0]がsticky。
    wire [12:0] pack_grs = is_bf16 ? {3'd0, bf16_pack_grs} : fp16_pack_grs;
    wire [11:0] packed_m = {1'b0, pack_grs[12:2]} + {11'd0, (pack_grs[1] & (pack_grs[0] | pack_grs[2]))};
    wire pack_carry = is_bf16 ? packed_m[8] : packed_m[11];
    wire signed [9:0] packed_e = (near_underflow ? 10'sd1 : biased_before) + $signed({9'd0, pack_carry});
    wire [9:0] packed_fraction = is_bf16 ? {3'd0, (pack_carry ? packed_m[7:1] : packed_m[6:0])}
                                       : (pack_carry ? packed_m[10:1] : packed_m[9:0]);
    // 正のInf: BF16=0x7f80、FP16=0x7c00。qNaN: BF16=0x7fc0、FP16=0x7e00。
    wire [14:0] inf = is_bf16 ? 15'd32640 : 15'd31744;
    wire [15:0] nan = is_bf16 ? 16'd32704 : 16'd32256;
    wire [14:0] normal_payload = is_bf16 ? {packed_e[7:0], packed_fraction[6:0]} : {packed_e[4:0], packed_fraction};
    wire [14:0] finite_payload = (biased_before < 10'sd0 || packed_m < (is_bf16 ? 12'd128 : 12'd1024)) ? 15'd0
                              : (packed_e >= (is_bf16 ? 10'sd255 : 10'sd31)) ? inf : normal_payload;

    // 6. 特殊値と無効opの選択（近似結果より優先する）
    // expの|x|>=128は両形式ともoverflow／FTZとなり、近似経路を使わない。
    wire is_nan = exponent_all_ones & !fraction_zero;
    wire negative_rsqrt = select_rsqrt & x[15] & !exponent_zero;
    wire exp_large = input_e >= 9'sd7;
    // exp(±0)=1: BF16=0x3f80、FP16=0x3c00。
    wire [15:0] exp_result = exponent_zero ? (is_bf16 ? 16'd16256 : 16'd15360)
                           : exp_large ? (x[15] ? 16'd0 : {1'b0, inf}) : {1'b0, finite_payload};
    wire [15:0] root_result = exponent_zero ? {x[15], inf}
                            : exponent_all_ones ? {(select_recip & x[15]), 15'd0}
                            : {(select_recip & x[15]), finite_payload};
    assign result = (!valid_op | is_nan | negative_rsqrt) ? nan : select_exp ? exp_result : root_result;
endmodule
