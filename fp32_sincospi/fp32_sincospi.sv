// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0

// IEEE 754 binary32 の sin(pi*x) または cos(pi*x) を求める組合せ回路。
// select_cos=0ではsin(pi*x)、select_cos=1ではcos(pi*x)をresultへ返す。
// * 丸め方式：有限入力に対してfaithful roundingを目標とする
// * subnormal：入力と出力のsubnormalを保持する
// * 特殊値：NaNと無限大にはcanonical qNaNを返す
// 例外フラグ・NaN payload・動的丸めmode指定は非対応。
// おおよその計算アルゴリズム：
// 1. |x| mod 2をQ31の位相へ変換し、cosでは正確に0.5を加える。
// 2. 対称性で0 <= u <= 0.5へ縮約し、65中心の三次式でsin(pi*u)を求める。
// 3. Q31で入力精度を保てない小さいsin入力は、sin(pi*x)/xを一次補間する。
module FP32SinCosPi(x, select_cos, result);
    input  wire[31:0] x;
    input  wire       select_cos;
    output wire[31:0] result;

    localparam [31:0] qnan = 32'h7fc00000;

// BEGIN GENERATED SINCOSPI TABLES
    localparam [25:0] pi_q24 = 26'd52707179;

    localparam [32:0] sine_table_q32 [0:64] = '{
        33'd0, 33'd105403774, 33'd210744057, 33'd315957395, // j = 0 .. j = 3
        33'd420980412, 33'd525749847, 33'd630202589, 33'd734275721, // j = 4 .. j = 7
        33'd837906553, 33'd941032661, 33'd1043591926, 33'd1145522571, // j = 8 .. j = 11
        33'd1246763195, 33'd1347252816, 33'd1446930903, 33'd1545737412, // j = 12 .. j = 15
        33'd1643612827, 33'd1740498191, 33'd1836335144, 33'd1931065957, // j = 16 .. j = 19
        33'd2024633568, 33'd2116981616, 33'd2208054473, 33'd2297797281, // j = 20 .. j = 23
        33'd2386155981, 33'd2473077351, 33'd2558509031, 33'd2642399561, // j = 24 .. j = 27
        33'd2724698408, 33'd2805355999, 33'd2884323748, 33'd2961554089, // j = 28 .. j = 31
        33'd3037000500, 33'd3110617535, 33'd3182360851, 33'd3252187232, // j = 32 .. j = 35
        33'd3320054617, 33'd3385922125, 33'd3449750080, 33'd3511500034, // j = 36 .. j = 39
        33'd3571134792, 33'd3628618433, 33'd3683916329, 33'd3736995171, // j = 40 .. j = 43
        33'd3787822988, 33'd3836369162, 33'd3882604450, 33'd3926501002, // j = 44 .. j = 47
        33'd3968032378, 33'd4007173558, 33'd4043900968, 33'd4078192482, // j = 48 .. j = 51
        33'd4110027446, 33'd4139386683, 33'd4166252509, 33'd4190608739, // j = 52 .. j = 55
        33'd4212440704, 33'd4231735252, 33'd4248480760, 33'd4262667143, // j = 56 .. j = 59
        33'd4274285855, 33'd4283329896, 33'd4289793820, 33'd4293673732, // j = 60 .. j = 63
        33'd4294967296 // j = 64
    };

    localparam [26:0] coefficient_b_table_q25 [0:64] = '{
        27'd105414357, 27'd105382608, 27'd105287381, 27'd105128732, // j = 0 .. j = 3
        27'd104906758, 27'd104621592, 27'd104273406, 27'd103862409, // j = 4 .. j = 7
        27'd103388850, 27'd102853013, 27'd102255221, 27'd101595834, // j = 8 .. j = 11
        27'd100875250, 27'd100093903, 27'd99252262, 27'd98350836, // j = 12 .. j = 15
        27'd97390167, 27'd96370834, 27'd95293450, 27'd94158665, // j = 16 .. j = 19
        27'd92967163, 27'd91719661, 27'd90416910, 27'd89059695, // j = 20 .. j = 23
        27'd87648835, 27'd86185177, 27'd84669606, 27'd83103032, // j = 24 .. j = 27
        27'd81486400, 27'd79820684, 27'd78106886, 27'd76346041, // j = 28 .. j = 31
        27'd74539207, 27'd72687473, 27'd70791955, 27'd68853795, // j = 32 .. j = 35
        27'd66874160, 27'd64854243, 27'd62795259, 27'd60698450, // j = 36 .. j = 39
        27'd58565079, 27'd56396430, 27'd54193810, 27'd51958546, // j = 40 .. j = 43
        27'd49691984, 27'd47395489, 27'd45070445, 27'd42718253, // j = 44 .. j = 47
        27'd40340328, 27'd37938104, 27'd35513027, 27'd33066559, // j = 48 .. j = 51
        27'd30600173, 27'd28115354, 27'd25613599, 27'd23096416, // j = 52 .. j = 55
        27'd20565321, 27'd18021838, 27'd15467499, 27'd12903843, // j = 56 .. j = 59
        27'd10332414, 27'd7754761, 27'd5172437, 27'd2586998, // j = 60 .. j = 63
        27'd0 // j = 64
    };

    localparam [19:0] coefficient_c_table_q16 [0:64] = '{
        20'sd0, -20'sd7937, -20'sd15869, -20'sd23791, // j = 0 .. j = 3
        -20'sd31699, -20'sd39588, -20'sd47454, -20'sd55290, // j = 4 .. j = 7
        -20'sd63094, -20'sd70859, -20'sd78582, -20'sd86257, // j = 8 .. j = 11
        -20'sd93880, -20'sd101447, -20'sd108953, -20'sd116393, // j = 12 .. j = 15
        -20'sd123763, -20'sd131058, -20'sd138274, -20'sd145408, // j = 16 .. j = 19
        -20'sd152453, -20'sd159407, -20'sd166265, -20'sd173022, // j = 20 .. j = 23
        -20'sd179675, -20'sd186221, -20'sd192653, -20'sd198970, // j = 24 .. j = 27
        -20'sd205167, -20'sd211241, -20'sd217187, -20'sd223002, // j = 28 .. j = 31
        -20'sd228683, -20'sd234227, -20'sd239629, -20'sd244887, // j = 32 .. j = 35
        -20'sd249997, -20'sd254957, -20'sd259763, -20'sd264413, // j = 36 .. j = 39
        -20'sd268903, -20'sd273232, -20'sd277396, -20'sd281392, // j = 40 .. j = 43
        -20'sd285220, -20'sd288875, -20'sd292357, -20'sd295662, // j = 44 .. j = 47
        -20'sd298789, -20'sd301737, -20'sd304502, -20'sd307084, // j = 48 .. j = 51
        -20'sd309481, -20'sd311692, -20'sd313715, -20'sd315549, // j = 52 .. j = 55
        -20'sd317193, -20'sd318646, -20'sd319907, -20'sd320975, // j = 56 .. j = 59
        -20'sd321850, -20'sd322531, -20'sd323018, -20'sd323310, // j = 60 .. j = 63
        -20'sd323407 // j = 64
    };

    localparam [10:0] coefficient_d_table_q7 [0:64] = '{
        -11'sd661, -11'sd661, -11'sd661, -11'sd660, // j = 0 .. j = 3
        -11'sd658, -11'sd656, -11'sd654, -11'sd652, // j = 4 .. j = 7
        -11'sd649, -11'sd645, -11'sd642, -11'sd638, // j = 8 .. j = 11
        -11'sd633, -11'sd628, -11'sd623, -11'sd617, // j = 12 .. j = 15
        -11'sd611, -11'sd605, -11'sd598, -11'sd591, // j = 16 .. j = 19
        -11'sd583, -11'sd576, -11'sd567, -11'sd559, // j = 20 .. j = 23
        -11'sd550, -11'sd541, -11'sd531, -11'sd521, // j = 24 .. j = 27
        -11'sd511, -11'sd501, -11'sd490, -11'sd479, // j = 28 .. j = 31
        -11'sd468, -11'sd456, -11'sd444, -11'sd432, // j = 32 .. j = 35
        -11'sd420, -11'sd407, -11'sd394, -11'sd381, // j = 36 .. j = 39
        -11'sd367, -11'sd354, -11'sd340, -11'sd326, // j = 40 .. j = 43
        -11'sd312, -11'sd297, -11'sd283, -11'sd268, // j = 44 .. j = 47
        -11'sd253, -11'sd238, -11'sd223, -11'sd207, // j = 48 .. j = 51
        -11'sd192, -11'sd176, -11'sd161, -11'sd145, // j = 52 .. j = 55
        -11'sd129, -11'sd113, -11'sd97, -11'sd81, // j = 56 .. j = 59
        -11'sd65, -11'sd49, -11'sd32, -11'sd16, // j = 60 .. j = 63
        11'sd0 // j = 64
    };

    localparam [10:0] small_correction_base_q24 [0:95] = '{
        11'd331, 11'd373, 11'd419, 11'd466, // E = -9, j = 0 .. E = -9, j = 3
        11'd517, 11'd570, 11'd625, 11'd683, // E = -9, j = 4 .. E = -9, j = 7
        11'd744, 11'd807, 11'd873, 11'd942, // E = -9, j = 8 .. E = -9, j = 11
        11'd1013, 11'd1087, 11'd1163, 11'd1242, // E = -9, j = 12 .. E = -9, j = 15
        11'd83, 11'd93, 11'd105, 11'd117, // E = -10, j = 0 .. E = -10, j = 3
        11'd129, 11'd142, 11'd156, 11'd171, // E = -10, j = 4 .. E = -10, j = 7
        11'd186, 11'd202, 11'd218, 11'd235, // E = -10, j = 8 .. E = -10, j = 11
        11'd253, 11'd272, 11'd291, 11'd310, // E = -10, j = 12 .. E = -10, j = 15
        11'd21, 11'd23, 11'd26, 11'd29, // E = -11, j = 0 .. E = -11, j = 3
        11'd32, 11'd36, 11'd39, 11'd43, // E = -11, j = 4 .. E = -11, j = 7
        11'd47, 11'd50, 11'd55, 11'd59, // E = -11, j = 8 .. E = -11, j = 11
        11'd63, 11'd68, 11'd73, 11'd78, // E = -11, j = 12 .. E = -11, j = 15
        11'd5, 11'd6, 11'd7, 11'd7, // E = -12, j = 0 .. E = -12, j = 3
        11'd8, 11'd9, 11'd10, 11'd11, // E = -12, j = 4 .. E = -12, j = 7
        11'd12, 11'd13, 11'd14, 11'd15, // E = -12, j = 8 .. E = -12, j = 11
        11'd16, 11'd17, 11'd18, 11'd19, // E = -12, j = 12 .. E = -12, j = 15
        11'd1, 11'd1, 11'd2, 11'd2, // E = -13, j = 0 .. E = -13, j = 3
        11'd2, 11'd2, 11'd2, 11'd3, // E = -13, j = 4 .. E = -13, j = 7
        11'd3, 11'd3, 11'd3, 11'd4, // E = -13, j = 8 .. E = -13, j = 11
        11'd4, 11'd4, 11'd5, 11'd5, // E = -13, j = 12 .. E = -13, j = 15
        11'd0, 11'd0, 11'd0, 11'd0, // E = -14, j = 0 .. E = -14, j = 3
        11'd1, 11'd1, 11'd1, 11'd1, // E = -14, j = 4 .. E = -14, j = 7
        11'd1, 11'd1, 11'd1, 11'd1, // E = -14, j = 8 .. E = -14, j = 11
        11'd1, 11'd1, 11'd1, 11'd1 // E = -14, j = 12 .. E = -14, j = 15
    };

    localparam [6:0] small_correction_delta_q24 [0:95] = '{
        7'd42, 7'd46, 7'd47, 7'd51, // E = -9, j = 0 .. E = -9, j = 3
        7'd53, 7'd55, 7'd58, 7'd61, // E = -9, j = 4 .. E = -9, j = 7
        7'd63, 7'd66, 7'd69, 7'd71, // E = -9, j = 8 .. E = -9, j = 11
        7'd74, 7'd76, 7'd79, 7'd81, // E = -9, j = 12 .. E = -9, j = 15
        7'd10, 7'd12, 7'd12, 7'd12, // E = -10, j = 0 .. E = -10, j = 3
        7'd13, 7'd14, 7'd15, 7'd15, // E = -10, j = 4 .. E = -10, j = 7
        7'd16, 7'd16, 7'd17, 7'd18, // E = -10, j = 8 .. E = -10, j = 11
        7'd19, 7'd19, 7'd19, 7'd21, // E = -10, j = 12 .. E = -10, j = 15
        7'd2, 7'd3, 7'd3, 7'd3, // E = -11, j = 0 .. E = -11, j = 3
        7'd4, 7'd3, 7'd4, 7'd4, // E = -11, j = 4 .. E = -11, j = 7
        7'd3, 7'd5, 7'd4, 7'd4, // E = -11, j = 8 .. E = -11, j = 11
        7'd5, 7'd5, 7'd5, 7'd5, // E = -11, j = 12 .. E = -11, j = 15
        7'd1, 7'd1, 7'd0, 7'd1, // E = -12, j = 0 .. E = -12, j = 3
        7'd1, 7'd1, 7'd1, 7'd1, // E = -12, j = 4 .. E = -12, j = 7
        7'd1, 7'd1, 7'd1, 7'd1, // E = -12, j = 8 .. E = -12, j = 11
        7'd1, 7'd1, 7'd1, 7'd2, // E = -12, j = 12 .. E = -12, j = 15
        7'd0, 7'd1, 7'd0, 7'd0, // E = -13, j = 0 .. E = -13, j = 3
        7'd0, 7'd0, 7'd1, 7'd0, // E = -13, j = 4 .. E = -13, j = 7
        7'd0, 7'd0, 7'd1, 7'd0, // E = -13, j = 8 .. E = -13, j = 11
        7'd0, 7'd1, 7'd0, 7'd0, // E = -13, j = 12 .. E = -13, j = 15
        7'd0, 7'd0, 7'd0, 7'd1, // E = -14, j = 0 .. E = -14, j = 3
        7'd0, 7'd0, 7'd0, 7'd0, // E = -14, j = 4 .. E = -14, j = 7
        7'd0, 7'd0, 7'd0, 7'd0, // E = -14, j = 8 .. E = -14, j = 11
        7'd0, 7'd0, 7'd0, 7'd0 // E = -14, j = 12 .. E = -14, j = 15
    };
// END GENERATED SINCOSPI TABLES

    // 固定長vectorの最上位1を返す。zero入力では0を返す。
    // subnormal正規化とbinary32 packerで同じpriority encoder処理を共有する。
    function automatic [5:0] highest_set_bit(input [52:0] value);
        integer bit_index;
        begin
            highest_set_bit = 6'd0;
            for (bit_index = 0; bit_index < 53; bit_index = bit_index+1)
                if (value[bit_index])
                    highest_set_bit = 6'(bit_index);
        end
    endfunction

    wire        x_sign = x[31];
    wire [7:0]  x_exponent = x[30:23];
    wire [22:0] x_fraction = x[22:0];
    wire        x_is_zero = {x_exponent, x_fraction} == 31'd0;
    wire        x_is_special = x_exponent == 8'hff;

    // subnormal入力を24-bitの1.xへ正規化し、その指数も同時に求める。
    wire [5:0] leading_index_wide = highest_set_bit({30'b0, x_fraction});
    wire [4:0] leading_index = leading_index_wide[4:0];
    wire [4:0] subnormal_shift = 5'd23-leading_index;
    wire [23:0] normalized_significand = x_exponent != 0
        ? {1'b1, x_fraction}
        : ({1'b0, x_fraction} << subnormal_shift);
    wire signed [8:0] normalized_exponent = x_exponent != 0
        ? $signed({1'b0, x_exponent})-9'sd127
        : $signed({4'b0000, leading_index})-9'sd149;

    // E>=-8ではM*2^(E+8)の下位32 bitが|x| mod 2の正確なQ31表現となる。
    // それより小さい入力のQ31化はcos経路だけで使うため、最近接へ丸める。
    wire [5:0] phase_left_shift = x_exponent >= 8'd119
        ? x_exponent[5:0]-6'd55 : 6'd0;
    wire [31:0] phase_left = {8'b0, normalized_significand}
        << phase_left_shift;
    wire [5:0] phase_right_shift = x_exponent < 8'd119
        ? 6'(8'd119-x_exponent) : 6'd0;
    wire [24:0] phase_right_biased = {1'b0, normalized_significand}
        + (25'd1 << (phase_right_shift-1'b1));
    wire [31:0] phase_abs = x_exponent >= 8'd151 ? 32'd0
        : x_exponent >= 8'd119 ? phase_left
        : x_exponent >= 8'd96
            ? ({7'b0, phase_right_biased} >> phase_right_shift)
            : 32'd0;

    // cos(pi*x)=sin(pi*(|x|+0.5))なので、浮動小数点加算器は不要である。
    wire [31:0] selected_phase = phase_abs
        + (select_cos ? 32'h40000000 : 32'd0);
    wire [30:0] cycle_fraction = selected_phase[30:0];
    wire [30:0] reduced_argument_q31 = cycle_fraction[30]
        ? ~cycle_fraction+31'd1 : cycle_fraction;
    wire [6:0] table_index = reduced_argument_q31[30:24]
        + {6'd0, reduced_argument_q31[23]};
    // 最近傍中心との差は[-2^23, 2^23)なのでsigned 24 bitで表せる。
    wire signed [23:0] table_delta_q31 =
        $signed({reduced_argument_q31[23], reduced_argument_q31[22:0]});

    wire [32:0] sine_q32 = sine_table_q32[table_index];
    wire [26:0] coefficient_b_q25 = coefficient_b_table_q25[table_index];
    wire signed [19:0] coefficient_c_q16 =
        $signed(coefficient_c_table_q16[table_index]);
    wire signed [10:0] coefficient_d_q7 =
        $signed(coefficient_d_table_q7[table_index]);

    // Q31では入力の有効桁を残せない|x|<2^-8のsinだけを別形式で計算する。
    // E=-9..-14はsin(pi*x)/xとpiとの差を16区間で一次補間し、それ以下は
    // 差がbinary32の1 ULPより十分小さいためpiをそのまま使う。
    wire use_small_sine = !select_cos && !x_is_zero && !x_is_special
        && x_exponent < 8'd119;
    wire small_has_correction = x_exponent >= 8'd113
        && x_exponent <= 8'd118;
    wire [6:0] small_table_address = small_has_correction
        ? {3'(8'd118-x_exponent), x_fraction[22:19]} : 7'd0;
    wire [10:0] small_correction_base = small_has_correction
        ? small_correction_base_q24[small_table_address] : 11'd0;
    wire [6:0] small_correction_delta = small_has_correction
        ? small_correction_delta_q24[small_table_address] : 7'd0;

    // 第1乗算器は通常経路のd*Dと、小入力経路の一次補間で共有する。
    wire signed [23:0] first_operand_a = use_small_sine
        ? $signed({1'b0, 4'b0, x_fraction[18:0]}) : table_delta_q31;
    wire signed [10:0] first_operand_b = use_small_sine
        ? $signed({1'b0, 3'b0, small_correction_delta}) : coefficient_d_q7;
    wire signed [34:0] first_product = first_operand_a*first_operand_b;

    wire [34:0] first_product_magnitude = first_product < 0
        ? $unsigned(-first_product) : $unsigned(first_product);
    wire [34:0] first_product_biased = first_product_magnitude+35'd2097152;
    wire [10:0] d_term_magnitude_q16 = first_product_biased[32:22];
    wire signed [11:0] d_term_q16 = first_product < 0
        ? -$signed({1'b0, d_term_magnitude_q16})
        :  $signed({1'b0, d_term_magnitude_q16});
    wire signed [19:0] c_plus_d_q16 = coefficient_c_q16
        + {{8{d_term_q16[11]}}, d_term_q16};

    // 第2乗算器で通常経路のd*(C+d*D)を作る。
    wire signed [43:0] second_product = table_delta_q31*c_plus_d_q16;
    wire [43:0] second_product_magnitude = second_product < 0
        ? $unsigned(-second_product) : $unsigned(second_product);
    wire [43:0] second_product_biased = second_product_magnitude+44'd2097152;
    wire [19:0] c_term_magnitude_q25 = second_product_biased[41:22];
    wire signed [20:0] c_term_q25 = second_product < 0
        ? -$signed({1'b0, c_term_magnitude_q25})
        :  $signed({1'b0, c_term_magnitude_q25});
    wire signed [27:0] b_plus_c_q25 = $signed({1'b0, coefficient_b_q25})
        + {{7{c_term_q25[20]}}, c_term_q25};

    wire [25:0] small_interpolation_biased = $unsigned(first_product[25:0])
        + 26'd262144;
    wire [6:0] small_interpolation_q24 = small_has_correction
        ? small_interpolation_biased[25:19] : 7'd0;
    wire [10:0] small_correction_q24 = small_correction_base
        + {4'b0, small_interpolation_q24};
    wire [25:0] small_factor_q24 = pi_q24
        - {{15{1'b0}}, small_correction_q24};

    // 第3乗算器は通常経路のd*(B+...)と、小入力経路のx*(sin(pi*x)/x)で共有する。
    wire signed [24:0] third_operand_a = use_small_sine
        ? $signed({1'b0, normalized_significand})
        : $signed({table_delta_q31[23], table_delta_q31});
    wire signed [27:0] third_operand_b = use_small_sine
        ? $signed({2'b00, small_factor_q24}) : b_plus_c_q25;
    wire signed [52:0] third_product = third_operand_a*third_operand_b;
    wire [52:0] third_product_magnitude = third_product < 0
        ? $unsigned(-third_product) : $unsigned(third_product);

    wire [52:0] third_product_biased = third_product_magnitude+53'd8388608;
    wire [25:0] correction_magnitude_q32 = third_product_biased[49:24];
    wire signed [26:0] correction_q32 = third_product < 0
        ? -$signed({1'b0, correction_magnitude_q32})
        :  $signed({1'b0, correction_magnitude_q32});
    wire signed [33:0] general_value_q32 = $signed({1'b0, sine_q32})
        + {{7{correction_q32[26]}}, correction_q32};
    wire use_full_precision = !use_small_sine && table_index == 0;

    // 3種類の内部Q形式を、整数magnitudeと二進scaleの組へ揃えてからbinary32化する。
    wire [33:0] general_magnitude_q32 = general_value_q32 < 0
        ? $unsigned(-general_value_q32) : $unsigned(general_value_q32);
    wire [52:0] magnitude = use_small_sine
        ? third_product_magnitude
        : use_full_precision
            ? third_product_magnitude
            : {19'b0, general_magnitude_q32};
    wire signed [8:0] value_scale = use_small_sine
        ? normalized_exponent-9'sd47
        : use_full_precision ? -9'sd56 : -9'sd32;

    wire [5:0] msb_index = highest_set_bit(magnitude);
    wire signed [8:0] result_exponent_unrounded =
        $signed({3'b000, msb_index})+value_scale;
    wire result_is_normal = result_exponent_unrounded >= -9'sd126;
    wire signed [8:0] subnormal_shift_signed = -(value_scale+9'sd149);
    wire [5:0] rounding_shift = result_is_normal
        ? msb_index-6'd23
        : $unsigned(subnormal_shift_signed[5:0]);
    wire [52:0] shifted_magnitude = magnitude >> rounding_shift;
    wire [5:0] guard_position = rounding_shift == 0
        ? 6'd0 : rounding_shift-6'd1;
    wire [52:0] sticky_mask = (53'd1 << guard_position)-53'd1;
    wire guard = rounding_shift == 0 ? 1'b0 : magnitude[guard_position];
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
    wire [30:0] finite_payload = result_is_normal
        ? {normal_biased_exponent, normal_fraction}
        : rounded_significand[23]
            ? {8'd1, 23'd0}
            : {8'd0, rounded_significand[22:0]};

    // sinは奇関数、cosは偶関数である。phaseの上位bitで半周期の符号も反映する。
    // 零点ではこの符号を保持し、周期境界の片側極限と整合するsigned zeroを返す。
    wire result_sign = selected_phase[31]^(x_sign&~select_cos);
    wire [31:0] finite_result = magnitude == 0
        ? {result_sign, 31'd0} : {result_sign, finite_payload};
    assign result = x_is_special ? qnan : finite_result;
endmodule
