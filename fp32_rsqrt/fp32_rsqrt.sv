// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0

// IEEE 754 binary32の逆数平方根1/sqrt(x)を求める組合せ回路。
// * 丸め方式：正のnormal入力に対してfaithful rounding
// * 単調性：+0から+Infまでの非負領域で単調非増加
// * subnormal：入力をsigned zeroとみなすFTZ仕様
// 負のnormalと-Infはcanonical qNaN、±0は±Infを返す。
module FP32Rsqrt(x, result);
    input  wire [31:0] x;
    output wire [31:0] result;

    localparam logic [30:0] zero_payload = 31'h00000000;
    localparam logic [30:0] inf_payload  = 31'h7f800000;
    localparam logic [31:0] qnan         = 32'h7fc00000;

    // index[5]は非バイアス指数の偶奇、index[4:0]は仮数の32区間である。
    // p=0では1/sqrt(m)、p=1では1/sqrt(2m)の誤差中心化したQ16切片を持つ。
    localparam logic [15:0] rsqrt_intercept_q16 [0:63] = '{
        16'hfffd,
        16'hfc15,
        16'hf859,
        16'hf4c6,
        16'hf15a,
        16'hee11,
        16'heaea,
        16'he7e2,
        16'he4f8,
        16'he228,
        16'hdf73,
        16'hdcd6,
        16'hda50,
        16'hd7e0,
        16'hd584,
        16'hd33b,
        16'hd105,
        16'hcee0,
        16'hcccc,
        16'hcac7,
        16'hc8d2,
        16'hc6eb,
        16'hc511,
        16'hc344,
        16'hc184,
        16'hbfcf,
        16'hbe26,
        16'hbc88,
        16'hbaf4,
        16'hb96a,
        16'hb7ea,
        16'hb673,
        16'hb503,
        16'hb240,
        16'haf9c,
        16'had15,
        16'haaa9,
        16'ha857,
        16'ha61c,
        16'ha3f7,
        16'ha1e7,
        16'h9feb,
        16'h9e01,
        16'h9c28,
        16'h9a5f,
        16'h98a5,
        16'h96fa,
        16'h955d,
        16'h93cc,
        16'h9248,
        16'h90d0,
        16'h8f63,
        16'h8e00,
        16'h8ca8,
        16'h8b59,
        16'h8a13,
        16'h88d6,
        16'h87a1,
        16'h8675,
        16'h8550,
        16'h8432,
        16'h831c,
        16'h820c,
        16'h8103
    };

    // 各区間のQ16切片差。11-bit区間内位置との積で一次補間する。
    localparam logic [9:0] rsqrt_delta_q16 [0:63] = '{
        10'h3e8,
        10'h3bc,
        10'h393,
        10'h36c,
        10'h349,
        10'h327,
        10'h308,
        10'h2eb,
        10'h2d0,
        10'h2b5,
        10'h29d,
        10'h286,
        10'h271,
        10'h25c,
        10'h249,
        10'h236,
        10'h225,
        10'h214,
        10'h205,
        10'h1f5,
        10'h1e8,
        10'h1da,
        10'h1cd,
        10'h1c0,
        10'h1b5,
        10'h1a9,
        10'h19e,
        10'h194,
        10'h18a,
        10'h180,
        10'h177,
        10'h16f,
        10'h2c4,
        10'h2a5,
        10'h287,
        10'h26c,
        10'h252,
        10'h23b,
        10'h225,
        10'h210,
        10'h1fc,
        10'h1ea,
        10'h1d9,
        10'h1c9,
        10'h1ba,
        10'h1ab,
        10'h19d,
        10'h191,
        10'h184,
        10'h178,
        10'h16d,
        10'h163,
        10'h158,
        10'h14f,
        10'h146,
        10'h13d,
        10'h135,
        10'h12c,
        10'h125,
        10'h11e,
        10'h116,
        10'h110,
        10'h109,
        10'h103
    };

    wire        x_sign = x[31];
    wire [7:0]  x_expo = x[30:23];
    wire [22:0] x_mant = x[22:0];
    wire [23:0] x_sig = { 1'b1, x_mant };

    // E=x_expo-127なので、Eの下位bitはx_expoの下位bitを反転した値になる。
    wire exponent_parity = ~x_expo[0];
    wire [5:0] table_index = { exponent_parity, x_mant[22:18] };
    wire [10:0] residual = x_mant[17:7];

    wire [20:0] interpolation_product =
        rsqrt_delta_q16[table_index] * residual;
    wire [9:0] interpolation = interpolation_product[20:11];
    wire [15:0] rsqrt_seed =
        rsqrt_intercept_q16[table_index] - { 6'b0, interpolation };

    // e0=t*y0^2-1を作る。y0^2はQ32、m*y0^2はQ55である。
    // p=1ではt=2mなので積を1 bit左shiftする。
    wire [31:0] seed_square = rsqrt_seed * rsqrt_seed;
    wire [55:0] seed_product = x_sig * seed_square;
    wire [56:0] scaled_seed_product = exponent_parity
                                     ? { seed_product, 1'b0 }
                                     : { 1'b0, seed_product };

    // 全入力でe0はsigned 44 bitに収まる。Q55の1.0は2^55であり、
    // mod 2^44では0なので、積の下位44 bitが差を取った二の補数値に一致する。
    wire signed [43:0] error_excess =
        $signed(scaled_seed_product[43:0]);

    // y1=y0-y0*e0/2。補正乗算ではseedをQ15、errorをQ29へ縮める。
    // 差を正確に作った後でだけ下位bitを落とす。
    wire [14:0] correction_seed = rsqrt_seed[15:1];
    wire signed [17:0] error_high = error_excess[43:26];
    wire signed [15:0] correction_seed_signed =
        $signed({ 1'b0, correction_seed });
    wire signed [33:0] correction_product =
        correction_seed_signed * error_high;
    wire signed [20:0] correction = correction_product[33:13];

    // Q32へ再構成し、最終Q23仮数化の0.5 LSBに相当する128を加える。
    wire signed [33:0] rsqrt_q32 =
        $signed({ 2'b00, rsqrt_seed, 16'b0 })
        - $signed({ { 13{correction[20]} }, correction })
        + 34'sd128;
    wire [24:0] normalized_sig = rsqrt_q32[32:8];

    // y1=1/sqrt(t)を2倍して[1,2)の仮数へする基準指数は126-q。
    // q=floor((x_expo-127)/2)を整理すると次の減算と右shiftになる。
    wire [8:0] base_expo_wide =
        (9'd380 - { 1'b0, x_expo } - { 8'b0, x_expo[0] }) >> 1;
    wire [7:0] base_expo = base_expo_wide[7:0];
    wire [7:0] normalized_expo = normalized_sig[24]
                               ? base_expo + 8'd1 : base_expo;
    wire [22:0] normalized_mant = normalized_sig[24]
                                ? 23'b0 : normalized_sig[22:0];
    wire [30:0] finite_payload = { normalized_expo, normalized_mant };

    // t=1、すなわちfraction=0かつEが偶数の入力は厳密な2の累乗を返す。
    wire exact_even_power = (~exponent_parity) & (x_mant == 0);
    wire [30:0] exact_power_payload = { base_expo + 8'd1, 23'b0 };

    wire x_is_nan = (x_expo == 8'hff) & (x_mant != 0);
    wire x_is_inf = (x_expo == 8'hff) & (x_mant == 0);
    wire x_is_zero_or_subnormal = x_expo == 0;
    wire x_is_negative_normal =
        x_sign & (x_expo != 0) & (x_expo != 8'hff);

    assign result = x_is_nan               ? qnan :
                    x_is_zero_or_subnormal ? { x_sign, inf_payload } :
                    x_is_inf               ? (x_sign ? qnan
                                                      : { 1'b0, zero_payload }) :
                    x_is_negative_normal   ? qnan :
                    exact_even_power       ? { 1'b0, exact_power_payload } :
                                              { 1'b0, finite_payload };
endmodule
