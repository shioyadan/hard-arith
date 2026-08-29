// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0

// DW_lp_fp_multifuncのlog2と同程度の誤差条件を、小さい単機能回路で狙う。
// 正のnormal入力だけを近似し、subnormal入力はFTZとして扱う。
module FP32Log2Lite (
    input  wire [31:0] x,
    output wire [31:0] result
);
    wire x_sign = x[31];
    wire [7:0] x_exponent = x[30:23];
    wire [22:0] x_fraction = x[22:0];
    wire signed [30:0] value_q22;
    // 仮数上位6 bitで64区間を選び、下位17 bitを区間中心からの
    // signed残差へ変換する。index生成は配線だけで済む。
    wire [5:0] table_index = x_fraction[22:17];
    wire signed [17:0] residual_wide = $signed({1'b0, x_fraction[16:0]}) - 18'sd65536;
    wire signed [16:0] residual = residual_wide[16:0];

    // BEGIN GENERATED LOG2 LITE TABLES
    // 係数はすべて最終和と同じ2^-22単位で格納する。
    // 実値の範囲だけに合わせて22/18/11 bitへ幅を縮めている。
    localparam [21:0] coefficient_0_table_q22 [0:63] = '{
        22'd47091,
        22'd140187,
        22'd231872,
        22'd322188,
        22'd411177,
        22'd498875,
        22'd585321,
        22'd670549,
        22'd754594,
        22'd837487,
        22'd919260,
        22'd999942,
        22'd1079563,
        22'd1158150,
        22'd1235729,
        22'd1312327,
        22'd1387966,
        22'd1462672,
        22'd1536467,
        22'd1609373,
        22'd1681411,
        22'd1752601,
        22'd1822963,
        22'd1892517,
        22'd1961280,
        22'd2029271,
        22'd2096506,
        22'd2163002,
        22'd2228776,
        22'd2293842,
        22'd2358216,
        22'd2421913,
        22'd2484945,
        22'd2547328,
        22'd2609075,
        22'd2670198,
        22'd2730709,
        22'd2790622,
        22'd2849947,
        22'd2908696,
        22'd2966880,
        22'd3024510,
        22'd3081596,
        22'd3138149,
        22'd3194178,
        22'd3249693,
        22'd3304703,
        22'd3359218,
        22'd3413246,
        22'd3466796,
        22'd3519876,
        22'd3572495,
        22'd3624660,
        22'd3676379,
        22'd3727659,
        22'd3778509,
        22'd3828935,
        22'd3878945,
        22'd3928545,
        22'd3977741,
        22'd4026540,
        22'd4074950,
        22'd4122974,
        22'd4170622
    };
    localparam signed [17:0] coefficient_1_table_q22 [0:63] = '{
        18'sd93818,
        18'sd92385,
        18'sd90996,
        18'sd89648,
        18'sd88339,
        18'sd87068,
        18'sd85833,
        18'sd84632,
        18'sd83465,
        18'sd82330,
        18'sd81225,
        18'sd80148,
        18'sd79101,
        18'sd78080,
        18'sd77085,
        18'sd76116,
        18'sd75170,
        18'sd74248,
        18'sd73348,
        18'sd72470,
        18'sd71612,
        18'sd70774,
        18'sd69956,
        18'sd69157,
        18'sd68375,
        18'sd67611,
        18'sd66864,
        18'sd66133,
        18'sd65418,
        18'sd64719,
        18'sd64034,
        18'sd63363,
        18'sd62707,
        18'sd62063,
        18'sd61434,
        18'sd60816,
        18'sd60211,
        18'sd59618,
        18'sd59036,
        18'sd58466,
        18'sd57906,
        18'sd57357,
        18'sd56818,
        18'sd56290,
        18'sd55771,
        18'sd55262,
        18'sd54762,
        18'sd54271,
        18'sd53788,
        18'sd53314,
        18'sd52848,
        18'sd52390,
        18'sd51942,
        18'sd51500,
        18'sd51064,
        18'sd50638,
        18'sd50218,
        18'sd49804,
        18'sd49397,
        18'sd48998,
        18'sd48604,
        18'sd48217,
        18'sd47835,
        18'sd47461
    };
    localparam signed [10:0] coefficient_2_table_q22 [0:63] = '{
        -11'sd727,
        -11'sd706,
        -11'sd685,
        -11'sd661,
        -11'sd645,
        -11'sd623,
        -11'sd607,
        -11'sd590,
        -11'sd576,
        -11'sd560,
        -11'sd546,
        -11'sd529,
        -11'sd515,
        -11'sd503,
        -11'sd489,
        -11'sd480,
        -11'sd465,
        -11'sd453,
        -11'sd443,
        -11'sd434,
        -11'sd425,
        -11'sd414,
        -11'sd402,
        -11'sd395,
        -11'sd385,
        -11'sd378,
        -11'sd369,
        -11'sd360,
        -11'sd354,
        -11'sd346,
        -11'sd338,
        -11'sd333,
        -11'sd323,
        -11'sd316,
        -11'sd312,
        -11'sd307,
        -11'sd299,
        -11'sd296,
        -11'sd290,
        -11'sd284,
        -11'sd278,
        -11'sd274,
        -11'sd267,
        -11'sd263,
        -11'sd258,
        -11'sd253,
        -11'sd246,
        -11'sd243,
        -11'sd238,
        -11'sd234,
        -11'sd230,
        -11'sd227,
        -11'sd222,
        -11'sd217,
        -11'sd211,
        -11'sd208,
        -11'sd203,
        -11'sd205,
        -11'sd204,
        -11'sd200,
        -11'sd192,
        -11'sd194,
        -11'sd188,
        -11'sd191
    };

    // END GENERATED LOG2 LITE TABLES

    // log2(m) ~= c0+r*(c1+r*c2)。各積は算術右shiftにより
    // 2^-22の出力scaleへ戻す。誤差条件と単調性は全仮数で確認する。
    wire signed [27:0] quadratic_product = residual * coefficient_2_table_q22[table_index];
    wire signed [10:0] quadratic_term = $signed(quadratic_product[27:17]);
    wire signed [17:0] horner_stage = coefficient_1_table_q22[table_index]
        + {{7{quadratic_term[10]}}, quadratic_term};
    wire signed [34:0] linear_product = residual * horner_stage;
    wire signed [17:0] correction = $signed(linear_product[34:17]);
    wire signed [23:0] log2_mantissa_q22 =
        $signed({2'b00, coefficient_0_table_q22[table_index]})
        + {{6{correction[17]}}, correction};
    wire signed [8:0] integer_log2 = $signed({1'b0, x_exponent}) - 9'sd127;
    wire signed [30:0] integer_log2_q22 = $signed({integer_log2, 22'b0});
    wire signed [30:0] approximation_q22 = integer_log2_q22
        + {{7{log2_mantissa_q22[23]}}, log2_mantissa_q22};
    assign value_q22 = (x_fraction == 0) ? integer_log2_q22 : approximation_q22;

    // signed Q22値をbinary32へround-to-nearest-evenでpackする。
    wire value_sign = value_q22[30];
    wire [30:0] magnitude = value_sign ? $unsigned(-value_q22) : $unsigned(value_q22);
    wire [4:0] msb_index =
        magnitude[30] ? 5'd30 : magnitude[29] ? 5'd29 :
        magnitude[28] ? 5'd28 : magnitude[27] ? 5'd27 :
        magnitude[26] ? 5'd26 : magnitude[25] ? 5'd25 :
        magnitude[24] ? 5'd24 : magnitude[23] ? 5'd23 :
        magnitude[22] ? 5'd22 : magnitude[21] ? 5'd21 :
        magnitude[20] ? 5'd20 : magnitude[19] ? 5'd19 :
        magnitude[18] ? 5'd18 : magnitude[17] ? 5'd17 :
        magnitude[16] ? 5'd16 : magnitude[15] ? 5'd15 :
        magnitude[14] ? 5'd14 : magnitude[13] ? 5'd13 :
        magnitude[12] ? 5'd12 : magnitude[11] ? 5'd11 :
        magnitude[10] ? 5'd10 : magnitude[9]  ? 5'd9  :
        magnitude[8]  ? 5'd8  : magnitude[7]  ? 5'd7  :
        magnitude[6]  ? 5'd6  : magnitude[5]  ? 5'd5  :
        magnitude[4]  ? 5'd4  : magnitude[3]  ? 5'd3  :
        magnitude[2]  ? 5'd2  : magnitude[1]  ? 5'd1  : 5'd0;

    wire shift_right = (msb_index >= 5'd23);
    wire [4:0] right_amount = shift_right ? msb_index - 5'd23 : 5'd0;
    wire [4:0] left_amount = shift_right ? 5'd0 : 5'd23 - msb_index;
    wire [30:0] shifted_right = magnitude >> right_amount;
    wire [30:0] shifted_left = magnitude << left_amount;
    wire [4:0] guard_index = (right_amount == 0) ? 5'd0 : right_amount - 5'd1;
    wire guard = (right_amount == 0) ? 1'b0 : magnitude[guard_index];
    wire [30:0] sticky_mask = (31'd1 << guard_index) - 31'd1;
    wire sticky = (right_amount <= 1) ? 1'b0 : |(magnitude & sticky_mask);
    wire [23:0] significand_before_round = shift_right ? shifted_right[23:0] : shifted_left[23:0];
    wire round_up = guard && (sticky || significand_before_round[0]);
    wire [24:0] rounded_significand = {1'b0, significand_before_round} + {24'b0, round_up};
    wire significand_carry = rounded_significand[24];
    wire [22:0] result_fraction = significand_carry
        ? rounded_significand[23:1]
        : rounded_significand[22:0];
    wire signed [9:0] unbiased_result_exponent =
        $signed({5'b0, msb_index}) - 10'sd22 + $signed({9'b0, significand_carry});
    wire signed [9:0] biased_result_exponent = unbiased_result_exponent + 10'sd127;
    wire [31:0] finite_result = (magnitude == 0)
        ? 32'h00000000
        : {value_sign, biased_result_exponent[7:0], result_fraction};

    // 特殊値を近似経路より優先する。zero/subnormalはFTZで-Inf、
    // 負の非零値はcanonical quiet NaNとする。
    assign result = (x_exponent == 8'h00) ? 32'hff800000
                  : (x_exponent == 8'hff && x_fraction != 0) ? 32'h7fc00000
                  : (x_exponent == 8'hff && !x_sign) ? 32'h7f800000
                  : x_sign ? 32'h7fc00000
                  : finite_result;
endmodule

