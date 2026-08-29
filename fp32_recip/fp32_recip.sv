// Copyright 2026 Ryota Shioya and Toru Koizumi
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
    // 全切片で共通するMSB=1を省き、下位13 bitだけを格納する。
    localparam logic[12:0] reciprocal_intercept_low_q14 [0:31] = '{
        13'h1ffd,
        13'h1e0e,
        13'h1c3a,
        13'h1a82,
        13'h18e1,
        13'h1758,
        13'h15e3,
        13'h1482,
        13'h1332,
        13'h11f2,
        13'h10c3,
        13'h0f9f,
        13'h0e8a,
        13'h0d82,
        13'h0c84,
        13'h0b92,
        13'h0aa9,
        13'h09cb,
        13'h08f5,
        13'h0827,
        13'h0761,
        13'h06a4,
        13'h05ec,
        13'h053c,
        13'h0491,
        13'h03ed,
        13'h034f,
        13'h02b5,
        13'h0222,
        13'h0192,
        13'h0107,
        13'h0081
    };

    // 傾きの約4倍の値域を二つのscaleへ分け、7 bitで格納する。
    // 区間0..12ではQ12、区間13..31ではQ13として解釈する。
    localparam logic[6:0] reciprocal_delta_scaled [0:31] = '{
        7'h7c,
        7'h75,
        7'h6e,
        7'h68,
        7'h62,
        7'h5d,
        7'h58,
        7'h54,
        7'h50,
        7'h4c,
        7'h49,
        7'h45,
        7'h42,
        7'h7f,
        7'h79,
        7'h74,
        7'h6f,
        7'h6b,
        7'h67,
        7'h63,
        7'h5f,
        7'h5c,
        7'h58,
        7'h55,
        7'h52,
        7'h4f,
        7'h4d,
        7'h4a,
        7'h48,
        7'h45,
        7'h43,
        7'h41
    };

    // 入力の分解。normal入力では x_sig は unsigned Q23 の [1,2) である。
    wire        x_sign = x[31];
    wire [7:0]  x_expo = x[30:23];
    wire [22:0] x_mant = x[22:0];
    wire [23:0] x_sig  = { 1'b1, x_mant };
    wire [4:0]  interval = x_mant[22:18];
    wire [9:0]  residual = x_mant[17:8];

    // 7x10 bit補間積をbankごとのscaleでQ14減算量へ戻す。
    // 区間内位置の下位8 bitは使わない。
    wire [16:0] interpolation_product =
        reciprocal_delta_scaled[interval] * residual;
    wire delta_q12_bank = interval <= 5'd12;
    wire [8:0] interpolation = delta_q12_bank
                             ? interpolation_product[16:8]
                             : { 1'b0, interpolation_product[16:9] };

    // 全seedのMSBも1なので、下位13 bitの減算後にMSBを復元する。
    wire [12:0] reciprocal_seed_low =
        reciprocal_intercept_low_q14[interval] - { 4'b0, interpolation };
    wire [13:0] reciprocal_seed = { 1'b1, reciprocal_seed_low };

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

    // 最後の+4はQ23へ落とす際の0.5 ULPに相当する。全仮数の整数解析で
    // faithfulとなる共通biasは+4だけである。
    wire signed [27:0] reciprocal_q27 =
        $signed({ 1'b0, reciprocal_seed, 13'b0 })
        - $signed({ { 12{correction[15]} }, correction })
        + 28'sd4;

    // reciprocal_q27 は 1/m のQ27なので、2/mの24-bit significandは[26:3]となる。
    wire [23:0] reciprocal_sig = reciprocal_q27[26:3];

    // m=1では2/mが2.0となるため、指数を一つ上げて仮数1.0を直接返す。
    // m>1では2/mが[1,2)なので通常のhidden bit位置へ収まる。
    // 二つの定数減算を、仮数zeroをcarry-inとする一つの指数演算へまとめる。
    wire x_mant_zero = ~|x_mant;
    wire [7:0] finite_expo =
        8'd253 - x_expo + { 7'b0, x_mant_zero };
    wire [30:0] finite_payload = {
        finite_expo,
        x_mant_zero ? 23'b0 : reciprocal_sig[22:0]
    };

    // FTZ仕様。normal入力の逆数がsubnormalになるのは、指数254の全入力と、
    // 指数253で仮数が1.0より大きい入力である。指数253・仮数0は最小normalを返す。
    // exponentとmantissaのzero/全1判定を特殊値decode全体で共有する。
    wire x_expo_all_one = &x_expo;
    wire x_expo_zero = ~|x_expo;
    wire x_is_nan = x_expo_all_one & ~x_mant_zero;
    wire x_is_inf = x_expo_all_one & x_mant_zero;
    wire result_is_ftz = x_expo == 8'd254
                       | (x_expo == 8'd253 & ~x_mant_zero);
    wire [30:0] result_payload = x_is_nan      ? qnan[30:0] :
                                 x_is_inf      ? zero_payload :
                                 x_expo_zero   ? inf_payload :
                                 result_is_ftz ? zero_payload : finite_payload;
    wire result_sign = x_is_nan ? 1'b0 : x_sign;
    assign result = { result_sign, result_payload };
endmodule
