// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0

// IEEE 754 binary32 の底2指数関数 2^x を求める組合せ回路。
// * 丸め方式：faithful rounding（無限精度値を挟む二つのbinary32値のどちらかを返す）
// * 単調性：非NaN入力に対して単調非減少を目標とする
// * 非正規化数出力：対応
// 例外flag、NaN payload保持、動的丸めmode指定は非対応。
// 1. n=round(64*x), n=64*q+j, r=x-n/64 と引数還元する。
// 2. 2^x=2^q*2^(j/64)*exp(ln(2)*r) を二次式で近似する。
module FP32Exp2(x, result);
    input  wire[31:0] x;
    output wire[31:0] result;

    localparam logic[31:0] zero = 32'h00000000;
    localparam logic[31:0] one  = 32'h3f800000;
    localparam logic[31:0] inf  = 32'h7f800000;
    localparam logic[31:0] qnan = 32'h7fc00000;

    // Q26 tableには、多項式と積の下向き誤差および最終丸めを補う微小biasを含める。
    // FP32Expの探索値を基点とし、2^xの全引数還元境界で単調になるようj=14を1だけ下げた。
    localparam logic [26:0] exp2_table_q26 [0:63] = '{
        27'h4000004, 27'h40b2695, 27'h4166c3a, 27'h421d14b,
        27'h42d5620, 27'h438fb12, 27'h444c079, 27'h450a6b0,
        27'h45cae14, 27'h468d6ff, 27'h47521d1, 27'h4818ee7,
        27'h48e1ea0, 27'h49ad15f, 27'h4a7a781, 27'h4b4a16f,
        27'h4c1bf87, 27'h4cf0231, 27'h4dc69d3, 27'h4e9f6d2,
        27'h4f7a998, 27'h505828d, 27'h513821d, 27'h521a8b3,
        27'h52ff6bb, 27'h53e6ca3, 27'h54d0adb, 27'h55bd1d3,
        27'h56ac1fc, 27'h579dbca, 27'h5891fb1, 27'h5988e25,
        27'h5a8279f, 27'h5b7ec95, 27'h5c7dd7f, 27'h5d7fadb,
        27'h5e84522, 27'h5f8bcd3, 27'h609626c, 27'h61a366c,
        27'h62b3956, 27'h63c6bab, 27'h64dcdf1, 27'h65f60ae,
        27'h6712466, 27'h68319a4, 27'h69540f2, 27'h6a79adb,
        27'h6ba27ec, 27'h6cce8b4, 27'h6dfddc2, 27'h6f307a9,
        27'h70666fd, 27'h719fc52, 27'h72dc83d, 27'h741cb58,
        27'h756063d, 27'h76a7986, 27'h77f25d3, 27'h7940bbf,
        27'h7a92bef, 27'h7be8701, 27'h7d41d9c, 27'h7e9f067
    };
    localparam logic[63:0] coefficient_up_mask   = 64'h7e9d67157815e428;
    localparam logic[63:0] coefficient_bit5_mask = 64'h82f64e5e3b0d227c;

    // 入力の分解。指数field 102～134では、近似本体に必要なQ29値を構成できる。
    wire       x_sign = x[31];
    wire [7:0] x_expo = x[30:23];
    wire[22:0] x_mant = x[22:0];
    wire[23:0] x_sig  = { 1'b1, x_mant };
    wire       in_range = x_expo >= 8'd102 & x_expo < 8'd135;

    // |x|をunsigned Q29へ移す。in_rangeではshift量が0～32となる。
    // 2^-29より下の端数は後段で使わないため、右shiftで捨ててよい。
    wire [5:0] scale_shift = 6'(8'd134 - x_expo);
    wire[36:0] x_q29 = { x_sig, 13'b0 } >> scale_shift;

    // n=round(64*|x|)をguard bitによる四捨五入で求める。
    // x_q29/2^22=128*|x|なので、bit22が1/2を表す。
    wire[14:0] index_window = x_q29[36:22];
    wire[14:0] n_abs = { 1'b0, index_window[14:1] }
                         + { 14'b0, index_window[0] };
    wire signed[15:0] n = x_sign ? -$signed({ 1'b0, n_abs })
                                  :  $signed({ 1'b0, n_abs });
    wire signed [9:0] q = n[15:6];
    wire        [5:0] j = n[5:0];

    // r_mag=|x|-n_abs/64をsigned Q28で得る。
    // n_abs/64のQ29表現は2^23の整数倍なので、差のmod 2^23はx_q29下位23bitに等しい。
    // 最近傍格子点との差は[-2^-7,2^-7)に収まり、下位bit列をsignedと読むだけで符号も復元できる。
    wire signed[21:0] r_mag_q28 = $signed(x_q29[22:1]);
    // 負入力のtieでは+rの端点がsigned 22-bitの正側範囲を1だけ超えるため、
    // 二の補数のnegateではなく一の補数で反転し、表現可能な最大値へ寄せる。
    wire signed[21:0] r_q28 = x_sign ? ~r_mag_q28 : r_mag_q28;

    // z=ln(2)*rをQ28で求める。ln(2)は21-bit Q21定数である。
    localparam logic[20:0] ln2_q21 = 21'h162e43;
    wire signed[43:0] z_product_q49 = r_q28 * $signed({ 1'b0, ln2_q21 });
    wire signed[21:0] z_q28 = z_product_q49[42:21];

    // exp(z)-1を z+z^2/2 で近似する。|z|<=ln(2)/128なので三次項は十分小さい。
    // 線形項は22bitを保ち、自乗だけを上位14bitへ縮める。
    wire       [21:0] z_abs_q28 = z_q28[21] ? -z_q28 : z_q28;
    wire       [13:0] square_operand = z_abs_q28[20:7];
    wire       [27:0] square_product = square_operand * square_operand;
    wire signed[21:0] polynomial_q28 = z_q28
        + $signed({ 9'b0, square_product[27:15] });
    wire signed[20:0] polynomial = polynomial_q28[21:1];

    // Table[j]+Table[j]*(z+z^2/2)をQ26で近似する。
    wire[26:0] table_q26 = exp2_table_q26[j];
    wire       coefficient_nonzero = j != 6'd4;
    wire       coefficient_up = coefficient_up_mask[j];
    wire [1:0] coefficient_epsilon = {
        coefficient_up, coefficient_nonzero & ~coefficient_up
    };
    wire [4:0] coefficient_low =
        table_q26[13:9] + { 3'b0, coefficient_epsilon };
    wire[17:0] coefficient = {
        table_q26[26:15], coefficient_bit5_mask[j], coefficient_low
    };
    wire signed[18:0] table_coefficient = $signed({ 1'b0, coefficient });
    wire signed[38:0] correction_product = table_coefficient * polynomial;
    wire signed[20:0] correction = correction_product[38:18];
    wire       [26:0] correction_wide = { { 6{correction[20]} }, correction };
    wire       [26:0] exp_mant_q26 = table_q26 + correction_wide;
    wire       [24:0] exp_mant = exp_mant_q26[26:2];

    // 2^qは乗算せず出力指数へ反映する。j=0かつr<0の場合だけ1bit左正規化する。
    wire signed [9:0] result_expo = exp_mant[24] ? q : q - 10'sd1;
    wire[22:0] normal_mant = exp_mant[24] ? exp_mant[23:1] : exp_mant[22:0];
    wire [7:0] subnormal_shift = 8'(-10'sd127 - result_expo);
    wire[22:0] subnormal_mant = { 1'b1, normal_mant[22:1] } >> subnormal_shift;
    wire       result_is_normal = result_expo >= -10'sd126;
    wire [7:0] biased_expo = result_expo[7:0] + 8'd127;
    wire[30:0] finite_payload = result_is_normal ? { biased_expo, normal_mant }
                                                 : { 8'b0, subnormal_mant };

    // 特殊値、小入力、overflow、完全underflowを処理する。
    wire       x_is_nan = x_expo == 8'hff & x_mant != 0;
    wire       result_is_inf = result_expo > 10'sd127;
    wire[31:0] in_range_result = result_is_inf ? inf : { 1'b0, finite_payload };
    wire[31:0] limit_result = x_sign ? zero : inf;
    wire[31:0] out_of_range_result = x_is_nan        ? qnan :
                                     x_expo < 8'd102 ? one : limit_result;

    assign result = in_range ? in_range_result : out_of_range_result;
endmodule
