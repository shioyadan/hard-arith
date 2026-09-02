// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0

// IEEE 754 binary32 の sin(pi*x) または cos(pi*x) を求める小型組合せ回路。
// select_cos=0ではsin(pi*x)、select_cos=1ではcos(pi*x)をresultへ返す。
// * 精度：有限入力に対する絶対誤差を4*2^-23以下とする
// * 特殊値：NaNと無限大にはcanonical qNaNを返す
// * zero、整数、半整数では厳密値を返す
// 例外フラグ・NaN payload・動的丸めmode指定は非対応。
// おおよその計算アルゴリズム：
// 1. |x| mod 2をQ23の位相へ変換し、cosでは正確に0.5を加える。
// 2. 対称性で0 <= u <= 0.5へ縮約する。
// 3. 64区間の中央ごとに最適化した二次式A+d*(B+d*C)でsin(pi*u)を求める。
module FP32SinCosPiLite(x, select_cos, result);
    input  wire [31:0] x;
    input  wire        select_cos;
    output wire [31:0] result;

// BEGIN GENERATED SINCOSPI LITE TABLES
    localparam [24:0] coefficient_a_table_q24 [0:63] = '{
        25'd205883, 25'd617524, 25'd1028792, 25'd1439442, // j = 0 .. j = 3
        25'd1849224, 25'd2257889, 25'd2665197, 25'd3070900, // j = 4 .. j = 7
        25'd3474754, 25'd3876514, 25'd4275935, 25'd4672785, // j = 8 .. j = 11
        25'd5066820, 25'd5457800, 25'd5845495, 25'd6229670, // j = 12 .. j = 15
        25'd6610089, 25'd6986529, 25'd7358758, 25'd7726558, // j = 16 .. j = 19
        25'd8089701, 25'd8447974, 25'd8801155, 25'd9149035, // j = 20 .. j = 23
        25'd9491403, 25'd9828059, 25'd10158791, 25'd10483404, // j = 24 .. j = 27
        25'd10801703, 25'd11113494, 25'd11418592, 25'd11716807, // j = 28 .. j = 31
        25'd12007970, 25'd12291900, 25'd12568422, 25'd12837377, // j = 32 .. j = 35
        25'd13098596, 25'd13351929, 25'd13597216, 25'd13834312, // j = 36 .. j = 39
        25'd14063075, 25'd14283368, 25'd14495057, 25'd14698015, // j = 40 .. j = 43
        25'd14892121, 25'd15077256, 25'd15253309, 25'd15420171, // j = 44 .. j = 47
        25'd15577749, 25'd15725939, 25'd15864657, 25'd15993819, // j = 48 .. j = 51
        25'd16113352, 25'd16223175, 25'd16323226, 25'd16413444, // j = 52 .. j = 55
        25'd16493772, 25'd16564170, 25'd16624590, 25'd16674992, // j = 56 .. j = 59
        25'd16715351, 25'd16745645, 25'd16765849, 25'd16775953 // j = 60 .. j = 63
    };

    localparam [16:0] coefficient_b_table_q15 [0:63] = '{
        17'd102934, 17'd102872, 17'd102748, 17'd102562, // j = 0 .. j = 3
        17'd102314, 17'd102005, 17'd101634, 17'd101202, // j = 4 .. j = 7
        17'd100710, 17'd100156, 17'd99542, 17'd98868, // j = 8 .. j = 11
        17'd98135, 17'd97342, 17'd96491, 17'd95582, // j = 12 .. j = 15
        17'd94615, 17'd93591, 17'd92511, 17'd91375, // j = 16 .. j = 19
        17'd90184, 17'd88938, 17'd87640, 17'd86288, // j = 20 .. j = 23
        17'd84885, 17'd83430, 17'd81925, 17'd80370, // j = 24 .. j = 27
        17'd78768, 17'd77117, 17'd75420, 17'd73679, // j = 28 .. j = 31
        17'd71892, 17'd70062, 17'd68190, 17'd66277, // j = 32 .. j = 35
        17'd64324, 17'd62332, 17'd60303, 17'd58237, // j = 36 .. j = 39
        17'd56137, 17'd54002, 17'd51835, 17'd49637, // j = 40 .. j = 43
        17'd47408, 17'd45152, 17'd42868, 17'd40558, // j = 44 .. j = 47
        17'd38224, 17'd35867, 17'd33488, 17'd31089, // j = 48 .. j = 51
        17'd28671, 17'd26237, 17'd23786, 17'd21320, // j = 52 .. j = 55
        17'd18842, 17'd16353, 17'd13854, 17'd11346, // j = 56 .. j = 59
        17'd8832, 17'd6313, 17'd3789, 17'd1263 // j = 60 .. j = 63
    };

    localparam [8:0] coefficient_c_table_q5 [0:63] = '{
        -9'sd2, -9'sd6, -9'sd10, -9'sd14, // j = 0 .. j = 3
        -9'sd18, -9'sd21, -9'sd25, -9'sd29, // j = 4 .. j = 7
        -9'sd33, -9'sd37, -9'sd40, -9'sd44, // j = 8 .. j = 11
        -9'sd48, -9'sd51, -9'sd55, -9'sd59, // j = 12 .. j = 15
        -9'sd62, -9'sd66, -9'sd69, -9'sd73, // j = 16 .. j = 19
        -9'sd76, -9'sd80, -9'sd83, -9'sd86, // j = 20 .. j = 23
        -9'sd89, -9'sd93, -9'sd96, -9'sd99, // j = 24 .. j = 27
        -9'sd102, -9'sd105, -9'sd108, -9'sd110, // j = 28 .. j = 31
        -9'sd113, -9'sd116, -9'sd118, -9'sd121, // j = 32 .. j = 35
        -9'sd123, -9'sd126, -9'sd128, -9'sd130, // j = 36 .. j = 39
        -9'sd132, -9'sd134, -9'sd136, -9'sd138, // j = 40 .. j = 43
        -9'sd140, -9'sd142, -9'sd144, -9'sd145, // j = 44 .. j = 47
        -9'sd147, -9'sd148, -9'sd149, -9'sd150, // j = 48 .. j = 51
        -9'sd152, -9'sd153, -9'sd154, -9'sd155, // j = 52 .. j = 55
        -9'sd155, -9'sd156, -9'sd157, -9'sd157, // j = 56 .. j = 59
        -9'sd157, -9'sd158, -9'sd158, -9'sd158 // j = 60 .. j = 63
    };
// END GENERATED SINCOSPI LITE TABLES

    wire        x_sign = x[31];
    wire [7:0]  x_exponent = x[30:23];
    wire [22:0] x_fraction = x[22:0];
    wire        x_is_special = x_exponent == 8'hff;

    wire [4:0] phase_left_shift = x_exponent >= 8'd127
        ? x_exponent[4:0]-5'd31 : 5'd0;
    wire [23:0] phase_left = {1'b1, x_fraction} << phase_left_shift;
    wire [4:0] phase_right_shift = x_exponent < 8'd127
        ? 5'(8'd127-x_exponent) : 5'd0;
    wire [24:0] phase_right_biased = {1'b0, 1'b1, x_fraction}
        + (25'd1 << (phase_right_shift-1'b1));
    wire [23:0] phase_right = phase_right_biased[24:1] >> (phase_right_shift-1'b1);
    wire [23:0] phase_abs = x_exponent >= 8'd151 ? 24'd0
        : x_exponent >= 8'd127 ? phase_left
        : x_exponent >= 8'd103 ? phase_right : 24'd0;

    wire [23:0] selected_phase = phase_abs
        + (select_cos ? 24'h400000 : 24'd0);
    wire [22:0] cycle_fraction = selected_phase[22:0];
    wire [22:0] reduced_argument_q23 = cycle_fraction[22]
        ? ~cycle_fraction+23'd1 : cycle_fraction;
    wire reduced_is_half = reduced_argument_q23 == 23'h400000;
    wire [5:0] table_index = reduced_is_half
        ? 6'd63 : reduced_argument_q23[21:16];
    wire signed [15:0] table_delta_q23 =
        $signed({~reduced_argument_q23[15], reduced_argument_q23[14:0]});

    wire [24:0] coefficient_a_q24 = coefficient_a_table_q24[table_index];
    wire [16:0] coefficient_b_magnitude_q15 = coefficient_b_table_q15[table_index];
    wire signed [8:0] coefficient_c_q5 =
        $signed(coefficient_c_table_q5[table_index]);

    wire signed [24:0] first_product = table_delta_q23*coefficient_c_q5;
    wire [24:0] first_product_magnitude = first_product < 0
        ? $unsigned(-first_product) : $unsigned(first_product);
    wire [24:0] first_product_biased = first_product_magnitude+25'd4096;
    wire [9:0] c_term_magnitude_q15 = first_product_biased[22:13];
    wire signed [10:0] c_term_q15 = first_product < 0
        ? -$signed({1'b0, c_term_magnitude_q15})
        :  $signed({1'b0, c_term_magnitude_q15});
    wire signed [17:0] b_plus_c_q15 =
        $signed({1'b0, coefficient_b_magnitude_q15})
        + {{7{c_term_q15[10]}}, c_term_q15};

    wire signed [33:0] second_product = table_delta_q23*b_plus_c_q15;
    wire [33:0] second_product_magnitude = second_product < 0
        ? $unsigned(-second_product) : $unsigned(second_product);
    wire [33:0] second_product_biased = second_product_magnitude+34'd8192;
    wire [17:0] correction_magnitude_q24 = second_product_biased[31:14];
    wire signed [18:0] correction_q24 = second_product < 0
        ? -$signed({1'b0, correction_magnitude_q24})
        :  $signed({1'b0, correction_magnitude_q24});
    wire signed [25:0] approximate_value_q24 = $signed({1'b0, coefficient_a_q24})
        + {{7{correction_q24[18]}}, correction_q24};

    wire reduced_is_zero = reduced_argument_q23 == 0;
    wire [25:0] magnitude = reduced_is_zero ? 26'd0
        : reduced_is_half ? 26'h1000000
        : approximate_value_q24 < 0
            ? $unsigned(-approximate_value_q24) : $unsigned(approximate_value_q24);

    integer bit_index;
    reg [5:0] msb_index;
    always @* begin
        msb_index = 6'd0;
        for (bit_index = 0; bit_index < 26; bit_index = bit_index+1)
            if (magnitude[bit_index])
                msb_index = 6'(bit_index);
    end

    wire signed [8:0] result_exponent_unrounded =
        $signed({3'b000, msb_index})-9'sd24;
    wire shift_right = msb_index >= 6'd23;
    wire [5:0] rounding_shift = shift_right
        ? msb_index-6'd23 : 6'd23-msb_index;
    wire [25:0] shifted_magnitude = shift_right
        ? magnitude >> rounding_shift : magnitude << rounding_shift;
    wire [5:0] guard_position = rounding_shift == 0
        ? 6'd0 : rounding_shift-6'd1;
    wire [25:0] sticky_mask = (26'd1 << guard_position)-26'd1;
    wire guard = !shift_right || rounding_shift == 0
        ? 1'b0 : magnitude[guard_position[4:0]];
    wire sticky = |(magnitude&sticky_mask);
    wire round_up = guard&(sticky|shifted_magnitude[0]);
    wire [24:0] rounded_significand = {1'b0, shifted_magnitude[23:0]}
        + {{24{1'b0}}, round_up};
    wire normal_carry = rounded_significand[24];
    wire signed [8:0] rounded_result_exponent = result_exponent_unrounded
        + $signed({8'b0, normal_carry});
    wire [7:0] normal_biased_exponent =
        8'(rounded_result_exponent+9'sd127);
    wire [22:0] normal_fraction = normal_carry
        ? rounded_significand[23:1] : rounded_significand[22:0];
    wire [30:0] finite_payload = {normal_biased_exponent, normal_fraction};

    wire result_sign = selected_phase[23]^(x_sign&~select_cos);
    wire [31:0] finite_result = magnitude == 0
        ? {result_sign, 31'd0} : {result_sign, finite_payload};
    assign result = x_is_special ? 32'h7fc00000 : finite_result;
endmodule
