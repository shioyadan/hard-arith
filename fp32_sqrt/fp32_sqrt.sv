// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0

// 指数偶奇別の二初期値と1回補正によりbinary32 sqrtを求める組合せ回路。
// 正のnormal入力ではfaithful roundingと単調非減少を保証する。
module FP32Sqrt(
    input  wire [31:0] x,
    output wire [31:0] result
);
    // index[4]は非バイアス指数の偶奇、index[3:0]は仮数の16区間である。
    // sqrt(t)の区間中央接線をQ16の左端切片と区間差分で保持する。
    localparam logic [16:0] sqrt_intercept_q16 [0:31] = '{
        17'h10008, 17'h107e8, 17'h10f8e, 17'h116fe,
        17'h11e3d, 17'h1254e, 17'h12c35, 17'h132f3,
        17'h1398d, 17'h14004, 17'h1465a, 17'h14c91,
        17'h152ab, 17'h158aa, 17'h15e8e, 17'h16459,
        17'h16a15, 17'h17538, 17'h18009, 17'h18a8e,
        17'h194cd, 17'h19ecc, 17'h1a88e, 17'h1b218,
        17'h1bb6e, 17'h1c492, 17'h1cd88, 17'h1d652,
        17'h1def3, 17'h1e76d, 17'h1efc2, 17'h1f7f4
    };

    localparam logic [11:0] sqrt_delta_q16 [0:31] = '{
        12'h7e1, 12'h7a6, 12'h771, 12'h73f,
        12'h711, 12'h6e7, 12'h6bf, 12'h69a,
        12'h677, 12'h656, 12'h637, 12'h61a,
        12'h5ff, 12'h5e4, 12'h5cb, 12'h5b4,
        12'hb24, 12'had1, 12'ha86, 12'ha40,
        12'h9ff, 12'h9c3, 12'h98a, 12'h956,
        12'h925, 12'h8f6, 12'h8cb, 12'h8a1,
        12'h87a, 12'h855, 12'h832, 12'h810
    };

    // 1/sqrt(t)も同じ区間中央接線で作り、補正時の除算を小さい乗算へ置き換える。
    localparam logic [15:0] invsqrt_intercept_q16 [0:31] = '{
        16'hffe9, 16'hf848, 16'hf14b, 16'headd,
        16'he4ec, 16'hdf69, 16'hda47, 16'hd57b,
        16'hd0fe, 16'hccc5, 16'hc8cc, 16'hc50b,
        16'hc17f, 16'hbe22, 16'hbaf0, 16'hb7e6,
        16'hb4f5, 16'haf8f, 16'haa9f, 16'ha613,
        16'ha1df, 16'h9df9, 16'h9a58, 16'h96f4,
        16'h93c7, 16'h90cb, 16'h8dfc, 16'h8b55,
        16'h88d2, 16'h8671, 16'h842f, 16'h8209
    };

    localparam logic [10:0] invsqrt_delta_q16 [0:31] = '{
        11'h7a4, 11'h6fe, 11'h66f, 11'h5f2,
        11'h584, 11'h523, 11'h4cc, 11'h47f,
        11'h439, 11'h3fa, 11'h3c1, 11'h38d,
        11'h35d, 11'h332, 11'h30a, 11'h2e5,
        11'h567, 11'h4f2, 11'h48d, 11'h434,
        11'h3e7, 11'h3a2, 11'h364, 11'h32e,
        11'h2fc, 11'h2d0, 11'h2a7, 11'h283,
        11'h261, 11'h242, 11'h226, 11'h20c
    };

    wire        x_sign = x[31];
    wire [7:0]  x_expo = x[30:23];
    wire [22:0] x_mant = x[22:0];
    wire [23:0] x_sig = { 1'b1, x_mant };

    // E=x_expo-127=2q+pなので、pはbiased exponentのLSBを反転した値になる。
    wire exponent_parity = ~x_expo[0];
    wire [4:0] table_index = { exponent_parity, x_mant[22:19] };

    // sqrt初期値はQ16係数をQ13へ丸め、8-bit区間内位置で補間する。
    wire [7:0] residual = x_mant[18:11];
    wire [9:0] sqrt_delta_q13 =
        { 1'b0, sqrt_delta_q16[table_index][11:3] }
        + { 9'b0, sqrt_delta_q16[table_index][2] };
    wire [16:0] sqrt_interpolation_product = sqrt_delta_q13 * residual;
    wire [8:0] sqrt_interpolation_q13 = sqrt_interpolation_product[16:8];
    wire [14:0] sqrt_seed_q13 =
        { 1'b0, sqrt_intercept_q16[table_index][16:3] }
        + { 14'b0, sqrt_intercept_q16[table_index][2] }
        + { 6'b0, sqrt_interpolation_q13 };
    wire [17:0] sqrt_seed = { sqrt_seed_q13, 3'b0 };

    // 逆数平方根初期値はQ14とし、7-bit区間内位置で補間する。
    wire [6:0] invsqrt_residual = x_mant[18:12];
    wire [15:0] invsqrt_interpolation_product =
        invsqrt_delta_q16[table_index][10:2] * invsqrt_residual;
    wire [13:0] invsqrt_seed_q14 =
        invsqrt_intercept_q16[table_index][15:2]
        - { 5'b0, invsqrt_interpolation_product[15:7] };

    // e=s0^2-tをQ32で作る。上位は同じ値同士で相殺するため、補正に必要な
    // signed 24 bitだけを差として作り、相殺部分の減算器を持たない。
    wire [35:0] sqrt_seed_square = sqrt_seed * sqrt_seed;
    wire [33:0] t_q32 = exponent_parity
                      ? { x_sig, 10'b0 }
                      : { 1'b0, x_sig, 9'b0 };
    wire signed [23:0] error_q32 =
        $signed(sqrt_seed_square[23:0] - t_q32[23:0]);

    // s1=s0-(s0^2-t)*y0/2。補正積では残差の下位7 bitを落とし、
    // 17x14 bit相当のsigned乗算だけを残す。
    wire signed [16:0] error_high = error_q32[23:7];
    wire signed [14:0] invsqrt_seed_signed =
        $signed({ 1'b0, invsqrt_seed_q14 });
    wire signed [31:0] correction_product =
        error_high * invsqrt_seed_signed;

    // Q49へ再構成し、11/32 ULPのbiasで量子化誤差をfaithful範囲の中央へ寄せる。
    wire signed [51:0] sqrt_q49 =
        $signed({ 1'b0, sqrt_seed, 33'b0 })
        - $signed({ { 11{correction_product[31]} },
                    correction_product, 9'b0 })
        + 52'sd23068672;
    wire [24:0] normalized_sig = sqrt_q49[50:26];

    // q=floor((E-p)/2)から出力biased exponentを作る。
    wire [8:0] base_expo_wide =
        ({ 1'b0, x_expo } + 9'd126 + { 8'b0, x_expo[0] }) >> 1;
    wire [7:0] base_expo = base_expo_wide[7:0];
    wire [7:0] normalized_expo = normalized_sig[24]
                               ? base_expo + 8'd1 : base_expo;
    wire [22:0] normalized_mant = normalized_sig[24]
                                ? 23'b0 : normalized_sig[22:0];
    wire [30:0] finite_payload = { normalized_expo, normalized_mant };

    wire x_is_nan = (x_expo == 8'hff) & (x_mant != 0);
    wire x_is_inf = (x_expo == 8'hff) & (x_mant == 0);
    wire x_is_zero_or_subnormal = x_expo == 0;
    wire x_is_negative_normal =
        x_sign & (x_expo != 0) & (x_expo != 8'hff);

    assign result = x_is_nan               ? 32'h7fc00000 :
                    x_is_zero_or_subnormal ? { x_sign, 31'b0 } :
                    x_is_inf               ? (x_sign ? 32'h7fc00000
                                                     : 32'h7f800000) :
                    x_is_negative_normal   ? 32'h7fc00000 :
                                              { 1'b0, finite_payload };
endmodule
