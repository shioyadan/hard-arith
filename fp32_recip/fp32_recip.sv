// Copyright 2026 Ryota Shioya
// SPDX-License-Identifier: Apache-2.0

// IEEE 754 binary32 の逆数 1/x を求める組合せ回路。
// * 丸め方式：結果が normal の範囲では faithful rounding
// * 単調性：正負それぞれの非 NaN 領域で単調非増加
// * subnormal：入力は signed zero とみなし、出力は signed zero へ flush する
// 例外フラグ・NaN のペイロード・動的丸めモード指定は非対応。
// recip(NaN) は canonical qNaN を返す。
// おおよその計算アルゴリズム：
// 1. 正規化仮数 m を 32 区間へ分け、区分一次補間で y0 ~= 1/m を求める。
// 2. y1 = y0 - y0*(m*y0-1) により Newton 反復を 1 回行う。
// 3. 2*y1 を binary32 仮数として丸め、入力指数の逆符号を反映する。
module FP32Recip(x, result);
    input  wire[31:0] x;
    output wire[31:0] result;

    localparam logic[30:0] zero_payload = 31'h00000000;
    localparam logic[30:0] inf_payload  = 31'h7f800000;
    localparam logic[31:0] qnan         = 32'h7fc00000;

    // 各区間で初期相対誤差が正負に釣り合うように調整したQ14切片。
    // 連続minimax直線をQ14へ量子化した後、全仮数で初期誤差を最小化している。
    localparam logic[13:0] reciprocal_intercept_q14 [0:31] = '{
        14'h3ffd,
        14'h3e0e,
        14'h3c3a,
        14'h3a82,
        14'h38e2,
        14'h3758,
        14'h35e3,
        14'h3482,
        14'h3332,
        14'h31f2,
        14'h30c2,
        14'h2fa0,
        14'h2e8a,
        14'h2d82,
        14'h2c84,
        14'h2b92,
        14'h2aa9,
        14'h29cb,
        14'h28f5,
        14'h2827,
        14'h2761,
        14'h26a4,
        14'h25ec,
        14'h253c,
        14'h2491,
        14'h23ed,
        14'h234f,
        14'h22b5,
        14'h2222,
        14'h2192,
        14'h2107,
        14'h2081
    };

    // Q14切片差の下位1 bitを省いたQ13傾き。
    localparam logic[7:0] reciprocal_delta_q13 [0:31] = '{
        8'hf8,
        8'hea,
        8'hdc,
        8'hd0,
        8'hc5,
        8'hba,
        8'hb1,
        8'ha8,
        8'ha0,
        8'h98,
        8'h91,
        8'h8b,
        8'h84,
        8'h7f,
        8'h79,
        8'h74,
        8'h6f,
        8'h6b,
        8'h67,
        8'h63,
        8'h5f,
        8'h5c,
        8'h58,
        8'h55,
        8'h52,
        8'h4f,
        8'h4d,
        8'h4a,
        8'h48,
        8'h45,
        8'h43,
        8'h41
    };

    // 入力の分解。normal入力では x_sig は unsigned Q23 の [1,2) である。
    wire        x_sign = x[31];
    wire [7:0]  x_expo = x[30:23];
    wire [22:0] x_mant = x[22:0];
    wire [23:0] x_sig  = { 1'b1, x_mant };
    wire [4:0]  interval = x_mant[22:18];
    wire [10:0] residual = x_mant[17:7];

    // Q13 delta * 11-bit residual / 2^10をQ14補間量にする。
    // 区間内位置の下位7 bitは使わない。
    wire [18:0] interpolation_product =
        reciprocal_delta_q13[interval] * residual;
    wire [8:0] interpolation = interpolation_product[18:10];
    wire [13:0] reciprocal_seed =
        reciprocal_intercept_q14[interval] - { 5'b0, interpolation };

    // m*y0-1はsigned 26 bitに収まる。Q37の1.0は2^37であり、mod 2^26では
    // 0になるため、24x14積の下位26 bitが差を取った後の二の補数残差と一致する。
    // 近い積から1.0を引く前に下位bitを捨てないので、零点付近の有効桁も保たれる。
    wire [37:0] seed_product = x_sig * reciprocal_seed;
    wire signed [25:0] error_excess = $signed(seed_product[25:0]);

    // y1 = y0-y0*(m*y0-1)。Q13 seedとsigned Q26 errorの積をQ39で作り、
    // 12 bit右へ落としてQ27補正量にする。seedは正値としてsigned化するため1 bit拡張する。
    wire [12:0] correction_seed = reciprocal_seed[13:1];
    wire signed [14:0] error_high = error_excess[25:11];
    wire signed [13:0] correction_seed_signed =
        $signed({ 1'b0, correction_seed });
    wire signed [28:0] correction_product =
        correction_seed_signed * error_high;
    wire signed [15:0] correction = correction_product[27:12];

    // 最後の+4はQ23へ落とす際の0.5 ULPに相当する。全仮数の整数解析では
    // +3から+4までがfaithfulであり、RNE一致数の多い+4を使う。
    wire signed [27:0] reciprocal_q27 =
        $signed({ 1'b0, reciprocal_seed, 13'b0 })
        - $signed({ { 12{correction[15]} }, correction })
        + 28'sd4;

    // reciprocal_q27 は 1/m のQ27なので、2/mの24-bit significandは[26:3]となる。
    wire [23:0] reciprocal_sig = reciprocal_q27[26:3];

    // m=1では2/mが2.0となるため、指数を一つ上げて仮数1.0を直接返す。
    // m>1では2/mが[1,2)なので通常のhidden bit位置へ収まる。
    wire [7:0] power_expo      = 8'd254 - x_expo;
    wire [7:0] reciprocal_expo = 8'd253 - x_expo;
    wire [30:0] finite_payload = x_mant == 0
                               ? { power_expo, 23'b0 }
                               : { reciprocal_expo, reciprocal_sig[22:0] };

    // FTZ仕様。normal入力の逆数がsubnormalになるのは、指数254の全入力と、
    // 指数253で仮数が1.0より大きい入力である。指数253・仮数0は最小normalを返す。
    wire x_is_nan = x_expo == 8'hff & x_mant != 0;
    wire x_is_inf = x_expo == 8'hff & x_mant == 0;
    wire x_is_zero_or_subnormal = x_expo == 0;
    wire result_is_ftz = x_expo == 8'd254
                       | (x_expo == 8'd253 & x_mant != 0);

    assign result = x_is_nan               ? qnan :
                    x_is_inf               ? { x_sign, zero_payload } :
                    x_is_zero_or_subnormal ? { x_sign, inf_payload } :
                    result_is_ftz           ? { x_sign, zero_payload } :
                                              { x_sign, finite_payload };
endmodule
