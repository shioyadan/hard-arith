// Copyright 2026 Ryota Shioya
// SPDX-License-Identifier: Apache-2.0

// binary32の自然指数関数exp(x)を求める、通常のln(2)引数削減方式。
//
// 既定構成は出力subnormalを+0へflushし、最終仮数を1-bit guardで丸める。
// clock、reset、valid/readyを持たない組合せ回路である。

module FP32Exp #(
    parameter bit SUPPORT_SUBNORMAL = 1'b0, // 1なら正のsubnormal出力を生成する
    parameter bit ROUND_OUTPUT = 1'b1       // 1なら最終仮数をguardで丸め、0なら切り捨てる
) (
    input  wire [31:0] x,                   // IEEE 754 binary32入力bit pattern
    output wire [31:0] result               // exp(x)のbinary32出力bit pattern
);
    // 引数削減用定数。
    localparam logic [18:0] INV_LN2_64_Q12 = 19'd378194; // round((64/ln(2))*2^12)
    localparam logic signed [34:0] LN2_BY_64_Q40 = 35'sd11908177887; // round((ln(2)/64)*2^40)
    localparam logic [31:0] ZERO = 32'h00000000;      // +0.0
    localparam logic [31:0] ONE  = 32'h3f800000;      // 1.0
    localparam logic [31:0] INF  = 32'h7f800000;      // +Inf
    localparam logic [31:0] QNAN = 32'h7fc00000;      // canonical quiet NaN

    // EXP2_TABLE_Q30[j] = round(2^(j/64)*2^30)を表す符号なしQ30テーブル。
    localparam logic [30:0] EXP2_TABLE_Q30 [0:63] = '{
        31'd1073741824, 31'd1085434106, 31'd1097253708, 31'd1109202018,
        31'd1121280436, 31'd1133490379, 31'd1145833280, 31'd1158310587,
        31'd1170923762, 31'd1183674286, 31'd1196563654, 31'd1209593378,
        31'd1222764986, 31'd1236080024, 31'd1249540052, 31'd1263146652,
        31'd1276901417, 31'd1290805962, 31'd1304861917, 31'd1319070932,
        31'd1333434672, 31'd1347954824, 31'd1362633090, 31'd1377471191,
        31'd1392470869, 31'd1407633882, 31'd1422962010, 31'd1438457051,
        31'd1454120821, 31'd1469955159, 31'd1485961921, 31'd1502142985,
        31'd1518500250, 31'd1535035634, 31'd1551751076, 31'd1568648537,
        31'd1585730000, 31'd1602997467, 31'd1620452965, 31'd1638098541,
        31'd1655936265, 31'd1673968228, 31'd1692196547, 31'd1710623359,
        31'd1729250827, 31'd1748081133, 31'd1767116489, 31'd1786359126,
        31'd1805811301, 31'd1825475297, 31'd1845353420, 31'd1865448001,
        31'd1885761398, 31'd1906295993, 31'd1927054196, 31'd1948038440,
        31'd1969251188, 31'd1990694927, 31'd2012372174, 31'd2034285470,
        31'd2056437387, 31'd2078830522, 31'd2101467502, 31'd2124350982
    };

    // 1. binary32を分解する。
    wire neg = x[31];                              // 入力の符号を取り出す
    wire [7:0] exp = x[30:23];                     // binary32の指数field
    wire [22:0] frac = x[22:0];                    // binary32の仮数field
    wire [23:0] sig = {1'b1, frac};                // hidden bit付き24-bit仮数
    wire in_range = exp >= 102 && exp < 134;       // 近似本体を使う入力範囲

    // 2. |x|*64/ln(2)を小数部7-bitの固定小数点窓へ取り出す。
    // [14:7]が整数部、[6:1]が小数部6-bit、[0]が丸め用guardである。
    wire [42:0] n_mul = sig * INV_LN2_64_Q12;       // 24x19-bit定数積
    wire [14:0] n_win =                             // 指数位置に合わせた15-bit窓
        n_mul[42:28] >> (8'd133 - exp);
    wire [15:0] n_abs = {2'b0, n_win[14:1]} +       // guardで最近傍化した絶対値側のn
                        {15'b0, n_win[0]};

    // 3. n=64*q+jへ分解する。
    wire signed [15:0] n = neg ?                    // x*64/ln(2)を丸めたsigned固定小数点コード
        -$signed(n_abs) : $signed(n_abs);
    wire signed [10:0] q = 11'(n >>> 6);            // 2^qへ使うsigned整数部
    wire [5:0] j = n[5:0];                          // 2^(j/64)へ使う小数部6-bit

    // 4. r=|x|-n_abs*ln(2)/64を高精度に相殺し、signed Q29で保持する。
    wire [47:0] x_abs =                              // 最大指数位置から右shiftした|x|のQ40値
        {1'b0, sig, 23'b0} >> (8'd133 - exp);
    wire signed [50:0] r_full =                      // 最近傍化により負にもなるsigned Q40残差
        $signed({3'b0, x_abs}) - 51'($signed(n_abs) * LN2_BY_64_Q40);
    wire signed [22:0] r = 23'(r_full >>> 11);       // signed 23-bit Q29残差

    // 5. r+r^2/2をQ30で計算する。
    wire signed [16:0] r2_half = 17'(                // Q58自乗から得るr^2/2の17-bit Q30値
        46'(r * r) >>> 29);
    wire signed [24:0] r_plus_half_r2 = neg ?        // 入力符号を線形項との加減算へ反映する
        $signed({8'b0, r2_half}) - $signed({r[22], r, 1'b0}) :
        $signed({8'b0, r2_half}) + $signed({r[22], r, 1'b0});

    // 6. e^x ~= 2^q*T[j]*(1+r+r^2/2)の仮数側を計算する。
    // 小さい補正だけを乗算し、1を含む主項T[j]は31-bit Q30のまま加える。
    wire [30:0] table_val = EXP2_TABLE_Q30[j];       // T[j]=2^(j/64)のQ30テーブル値
    wire signed [26:0] t_r_poly = 27'(               // T[j]*(r+r^2/2)のsigned Q30補正値
        48'($signed({1'b0, table_val[30:9]}) * r_plus_half_r2) >>> 21);
    wire [31:0] exp_mant = 32'(                      // T[j]*(1+r+r^2/2)の32-bit Q30値
        $signed({1'b0, table_val})
        + $signed({{5{t_r_poly[26]}}, t_r_poly}));

    // 7. 2^qを指数へ反映し、24-bit仮数と1-bit guardを取り出す。
    wire signed [10:0] out_exp = exp_mant[31] ? q + 1 : // 正規化後のバイアスなし指数
        !exp_mant[30] ? q - 1 : q;
    wire [24:0] sig_guard = exp_mant[31] ?           // 正規化後の24-bit仮数とguard
        exp_mant[31:7] : !exp_mant[30] ?
        exp_mant[29:5] : exp_mant[30:6];
    wire [24:0] rounded_sig =                        // 既定ではguard=1なら仮数を1増やす
        {1'b0, sig_guard[24:1]} + {24'b0, ROUND_OUTPUT && sig_guard[0]};
    wire [23:0] out_sig = rounded_sig[24] ?          // 丸めcarry時に再正規化する
        rounded_sig[24:1] : rounded_sig[23:0];
    wire signed [10:0] rounded_exp = out_exp +       // 丸めcarryを指数へ反映する
        $signed({10'b0, rounded_sig[24]});
    wire [4:0] sub_shift = 5'(-11'sd126 - out_exp); // subnormal出力の右shift量
    wire [24:0] sub_sig_guard =                      // subnormal位置へずらした仮数とguard
        sig_guard >> sub_shift;
    wire [23:0] sub_sig = sub_sig_guard[24:1] +      // shift後も同じ設定で丸める
        {23'b0, ROUND_OUTPUT && sub_sig_guard[0]};

    // 8. 特殊値、範囲外の定数値、近似結果を選ぶ。
    wire [31:0] special_out = frac != 0 ? QNAN :     // NaN
                              neg ? ZERO : INF;      // -Inf / +Inf
    wire [31:0] range_out = exp < 102 ? ONE :        // 微小入力
                            neg ? ZERO : INF;        // 大きな負入力 / 正入力
    wire is_overflow = rounded_exp > 127;            // binary32でoverflowする範囲
    wire is_normal = rounded_exp >= -126;            // normalとして表現できる範囲
    wire is_subnormal = SUPPORT_SUBNORMAL &&         // parameterが1ならsubnormalを残す
                        out_exp >= -149;
    wire [31:0] normal_out =                         // normalのbinary32 pack結果
        {1'b0, rounded_exp[7:0] + 8'd127, out_sig[22:0]};
    wire [31:0] subnormal_out = {8'b0, sub_sig};     // subnormalのbinary32 pack結果
    wire [31:0] calc_out = is_overflow ? INF :       // 近似結果を出力分類へ写す
                             is_normal ? normal_out :
                             is_subnormal ? subnormal_out : ZERO;
    assign result = exp == 8'hff ? special_out :     // NaN / Inf
                    in_range ? calc_out : range_out;  // 近似結果 / 範囲外の定数値
endmodule
