// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0

// IEEE 754 binary32 の底2対数 log2(x) を求める組合せ回路。
// * 丸め方式：正の有限入力に対して faithful rounding
// * 単調性：正の入力領域で単調非減少
// * subnormal：正の subnormal 入力を正規化して計算する
// 例外フラグ・NaN のペイロード・動的丸めモード指定は非対応。
// log2(NaN) と負の入力は canonical qNaN を返す。
// おおよその計算アルゴリズム：
// 1. x = 2^q*m、1/sqrt(2) <= m < sqrt(2) となるように正規化する。
// 2. m に最も近い table 中心 c を選び、18-bit Q24 の差分 d = m-c を作る。
// 3. q+L[c]+d*(A[c]+d*(B[c]+d*C[c])) を計算して binary32 へ丸める。
module FP32Log2(x, result);
    input  wire[31:0] x;
    output wire[31:0] result;

    localparam [31:0] zero    = 32'h00000000;
    localparam [31:0] inf     = 32'h7f800000;
    localparam [31:0] neg_inf = 32'hff800000;
    localparam [31:0] qnan    = 32'h7fc00000;

// BEGIN GENERATED LOG2 TABLES
    localparam [23:0] sqrt2_q23 = 24'd11863284;

    localparam [34:0] logarithm_table_q34 [0:90] = '{
        -35'sd8456023693, // j = -37
        -35'sd8185143269, // j = -36
        -35'sd7917191340, // j = -35
        -35'sd7652105261, // j = -34
        -35'sd7389824379, // j = -33
        -35'sd7130289944, // j = -32
        -35'sd6873445033, // j = -31
        -35'sd6619234476, // j = -30
        -35'sd6367604781, // j = -29
        -35'sd6118504070, // j = -28
        -35'sd5871882015, // j = -27
        -35'sd5627689773, // j = -26
        -35'sd5385879932, // j = -25
        -35'sd5146406455, // j = -24
        -35'sd4909224625, // j = -23
        -35'sd4674290998, // j = -22
        -35'sd4441563353, // j = -21
        -35'sd4211000648, // j = -20
        -35'sd3982562975, // j = -19
        -35'sd3756211520, // j = -18
        -35'sd3531908522, // j = -17
        -35'sd3309617238, // j = -16
        -35'sd3089301902, // j = -15
        -35'sd2870927696, // j = -14
        -35'sd2654460712, // j = -13
        -35'sd2439867925, // j = -12
        -35'sd2227117159, // j = -11
        -35'sd2016177060, // j = -10
        -35'sd1807017067, // j = -9
        -35'sd1599607387, // j = -8
        -35'sd1393918970, // j = -7
        -35'sd1189923480, // j = -6
        -35'sd987593278, // j = -5
        -35'sd786901396, // j = -4
        -35'sd587821514, // j = -3
        -35'sd390327942, // j = -2
        -35'sd194395601, // j = -1
        35'sd0, // j = 0
        35'sd192882779, // j = 1
        35'sd384276102, // j = 2
        35'sd574202794, // j = 3
        35'sd762685163, // j = 4
        35'sd949745010, // j = 5
        35'sd1135403647, // j = 6
        35'sd1319681909, // j = 7
        35'sd1502600171, // j = 8
        35'sd1684178361, // j = 9
        35'sd1864435971, // j = 10
        35'sd2043392070, // j = 11
        35'sd2221065319, // j = 12
        35'sd2397473979, // j = 13
        35'sd2572635924, // j = 14
        35'sd2746568652, // j = 15
        35'sd2919289296, // j = 16
        35'sd3090814631, // j = 17
        35'sd3261161089, // j = 18
        35'sd3430344764, // j = 19
        35'sd3598381422, // j = 20
        35'sd3765286511, // j = 21
        35'sd3931075170, // j = 22
        35'sd4095762234, // j = 23
        35'sd4259362248, // j = 24
        35'sd4421889467, // j = 25
        35'sd4583357869, // j = 26
        35'sd4743781161, // j = 27
        35'sd4903172785, // j = 28
        35'sd5061545925, // j = 29
        35'sd5218913514, // j = 30
        35'sd5375288242, // j = 31
        35'sd5530682557, // j = 32
        35'sd5685108677, // j = 33
        35'sd5838578592, // j = 34
        35'sd5991104070, // j = 35
        35'sd6142696666, // j = 36
        35'sd6293367720, // j = 37
        35'sd6443128369, // j = 38
        35'sd6591989550, // j = 39
        35'sd6739962002, // j = 40
        35'sd6887056274, // j = 41
        35'sd7033282728, // j = 42
        35'sd7178651544, // j = 43
        35'sd7323172724, // j = 44
        35'sd7466856094, // j = 45
        35'sd7609711315, // j = 46
        35'sd7751747876, // j = 47
        35'sd7892975107, // j = 48
        35'sd8033402180, // j = 49
        35'sd8173038110, // j = 50
        35'sd8311891763, // j = 51
        35'sd8449971853, // j = 52
        35'sd8587286952 // j = 53
    };

    localparam [29:0] coefficient_a_table_q27 [0:90] = '{
        30'sd272366067, // j = -37
        30'sd269405566, // j = -36
        30'sd266508732, // j = -35
        30'sd263673533, // j = -34
        30'sd260898022, // j = -33
        30'sd258180334, // j = -32
        30'sd255518681, // j = -31
        30'sd252911348, // j = -30
        30'sd250356688, // j = -29
        30'sd247853121, // j = -28
        30'sd245399129, // j = -27
        30'sd242993256, // j = -26
        30'sd240634098, // j = -25
        30'sd238320308, // j = -24
        30'sd236050591, // j = -23
        30'sd233823699, // j = -22
        30'sd231638431, // j = -21
        30'sd229493630, // j = -20
        30'sd227388184, // j = -19
        30'sd225321019, // j = -18
        30'sd223291100, // j = -17
        30'sd221297429, // j = -16
        30'sd219339045, // j = -15
        30'sd217415018, // j = -14
        30'sd215524453, // j = -13
        30'sd213666483, // j = -12
        30'sd211840274, // j = -11
        30'sd210045018, // j = -10
        30'sd208279933, // j = -9
        30'sd206544267, // j = -8
        30'sd204837290, // j = -7
        30'sd203158296, // j = -6
        30'sd201506602, // j = -5
        30'sd199881549, // j = -4
        30'sd198282497, // j = -3
        30'sd196708826, // j = -2
        30'sd195159938, // j = -1
        30'sd193635251, // j = 0
        30'sd192134202, // j = 1
        30'sd190656247, // j = 2
        30'sd189200856, // j = 3
        30'sd187767516, // j = 4
        30'sd186355730, // j = 5
        30'sd184965015, // j = 6
        30'sd183594904, // j = 7
        30'sd182244942, // j = 8
        30'sd180914687, // j = 9
        30'sd179603711, // j = 10
        30'sd178311598, // j = 11
        30'sd177037943, // j = 12
        30'sd175782355, // j = 13
        30'sd174544451, // j = 14
        30'sd173323861, // j = 15
        30'sd172120223, // j = 16
        30'sd170933187, // j = 17
        30'sd169762411, // j = 18
        30'sd168607565, // j = 19
        30'sd167468325, // j = 20
        30'sd166344376, // j = 21
        30'sd165235414, // j = 22
        30'sd164141140, // j = 23
        30'sd163061264, // j = 24
        30'sd161995504, // j = 25
        30'sd160943585, // j = 26
        30'sd159905239, // j = 27
        30'sd158880206, // j = 28
        30'sd157868230, // j = 29
        30'sd156869064, // j = 30
        30'sd155882466, // j = 31
        30'sd154908200, // j = 32
        30'sd153946038, // j = 33
        30'sd152995754, // j = 34
        30'sd152057129, // j = 35
        30'sd151129952, // j = 36
        30'sd150214013, // j = 37
        30'sd149309109, // j = 38
        30'sd148415042, // j = 39
        30'sd147531619, // j = 40
        30'sd146658651, // j = 41
        30'sd145795953, // j = 42
        30'sd144943345, // j = 43
        30'sd144100652, // j = 44
        30'sd143267700, // j = 45
        30'sd142444322, // j = 46
        30'sd141630355, // j = 47
        30'sd140825637, // j = 48
        30'sd140030012, // j = 49
        30'sd139243326, // j = 50
        30'sd138465431, // j = 51
        30'sd137696178, // j = 52
        30'sd136935426 // j = 53
    };

    localparam [18:0] coefficient_b_table_q17 [0:90] = '{
        -19'sd187065, // j = -37
        -19'sd183020, // j = -36
        -19'sd179105, // j = -35
        -19'sd175315, // j = -34
        -19'sd171643, // j = -33
        -19'sd168086, // j = -32
        -19'sd164638, // j = -31
        -19'sd161296, // j = -30
        -19'sd158053, // j = -29
        -19'sd154908, // j = -28
        -19'sd151856, // j = -27
        -19'sd148893, // j = -26
        -19'sd146016, // j = -25
        -19'sd143221, // j = -24
        -19'sd140506, // j = -23
        -19'sd137868, // j = -22
        -19'sd135303, // j = -21
        -19'sd132809, // j = -20
        -19'sd130383, // j = -19
        -19'sd128023, // j = -18
        -19'sd125727, // j = -17
        -19'sd123492, // j = -16
        -19'sd121316, // j = -15
        -19'sd119197, // j = -14
        -19'sd117133, // j = -13
        -19'sd115122, // j = -12
        -19'sd113163, // j = -11
        -19'sd111253, // j = -10
        -19'sd109391, // j = -9
        -19'sd107575, // j = -8
        -19'sd105804, // j = -7
        -19'sd104077, // j = -6
        -19'sd102392, // j = -5
        -19'sd100747, // j = -4
        -19'sd99141, // j = -3
        -19'sd97574, // j = -2
        -19'sd96043, // j = -1
        -19'sd94548, // j = 0
        -19'sd93088, // j = 1
        -19'sd91662, // j = 2
        -19'sd90268, // j = 3
        -19'sd88905, // j = 4
        -19'sd87573, // j = 5
        -19'sd86271, // j = 6
        -19'sd84998, // j = 7
        -19'sd83752, // j = 8
        -19'sd82534, // j = 9
        -19'sd81342, // j = 10
        -19'sd80176, // j = 11
        -19'sd79035, // j = 12
        -19'sd77918, // j = 13
        -19'sd76824, // j = 14
        -19'sd75753, // j = 15
        -19'sd74705, // j = 16
        -19'sd73678, // j = 17
        -19'sd72672, // j = 18
        -19'sd71687, // j = 19
        -19'sd70721, // j = 20
        -19'sd69775, // j = 21
        -19'sd68848, // j = 22
        -19'sd67939, // j = 23
        -19'sd67048, // j = 24
        -19'sd66175, // j = 25
        -19'sd65318, // j = 26
        -19'sd64478, // j = 27
        -19'sd63654, // j = 28
        -19'sd62846, // j = 29
        -19'sd62053, // j = 30
        -19'sd61275, // j = 31
        -19'sd60511, // j = 32
        -19'sd59762, // j = 33
        -19'sd59026, // j = 34
        -19'sd58304, // j = 35
        -19'sd57595, // j = 36
        -19'sd56899, // j = 37
        -19'sd56216, // j = 38
        -19'sd55545, // j = 39
        -19'sd54885, // j = 40
        -19'sd54238, // j = 41
        -19'sd53601, // j = 42
        -19'sd52976, // j = 43
        -19'sd52362, // j = 44
        -19'sd51759, // j = 45
        -19'sd51165, // j = 46
        -19'sd50582, // j = 47
        -19'sd50009, // j = 48
        -19'sd49446, // j = 49
        -19'sd48892, // j = 50
        -19'sd48347, // j = 51
        -19'sd47811, // j = 52
        -19'sd47284 // j = 53
    };

    localparam [9:0] coefficient_c_table_q8 [0:90] = '{
        10'sd343, // j = -37
        10'sd332, // j = -36
        10'sd321, // j = -35
        10'sd311, // j = -34
        10'sd301, // j = -33
        10'sd292, // j = -32
        10'sd283, // j = -31
        10'sd274, // j = -30
        10'sd266, // j = -29
        10'sd258, // j = -28
        10'sd251, // j = -27
        10'sd243, // j = -26
        10'sd236, // j = -25
        10'sd230, // j = -24
        10'sd223, // j = -23
        10'sd217, // j = -22
        10'sd211, // j = -21
        10'sd205, // j = -20
        10'sd199, // j = -19
        10'sd194, // j = -18
        10'sd189, // j = -17
        10'sd184, // j = -16
        10'sd179, // j = -15
        10'sd174, // j = -14
        10'sd170, // j = -13
        10'sd165, // j = -12
        10'sd161, // j = -11
        10'sd157, // j = -10
        10'sd153, // j = -9
        10'sd149, // j = -8
        10'sd146, // j = -7
        10'sd142, // j = -6
        10'sd139, // j = -5
        10'sd135, // j = -4
        10'sd132, // j = -3
        10'sd129, // j = -2
        10'sd126, // j = -1
        10'sd123, // j = 0
        10'sd120, // j = 1
        10'sd118, // j = 2
        10'sd115, // j = 3
        10'sd112, // j = 4
        10'sd110, // j = 5
        10'sd107, // j = 6
        10'sd105, // j = 7
        10'sd103, // j = 8
        10'sd100, // j = 9
        10'sd98, // j = 10
        10'sd96, // j = 11
        10'sd94, // j = 12
        10'sd92, // j = 13
        10'sd90, // j = 14
        10'sd88, // j = 15
        10'sd86, // j = 16
        10'sd85, // j = 17
        10'sd83, // j = 18
        10'sd81, // j = 19
        10'sd80, // j = 20
        10'sd78, // j = 21
        10'sd76, // j = 22
        10'sd75, // j = 23
        10'sd74, // j = 24
        10'sd72, // j = 25
        10'sd71, // j = 26
        10'sd69, // j = 27
        10'sd68, // j = 28
        10'sd67, // j = 29
        10'sd65, // j = 30
        10'sd64, // j = 31
        10'sd63, // j = 32
        10'sd62, // j = 33
        10'sd61, // j = 34
        10'sd60, // j = 35
        10'sd59, // j = 36
        10'sd57, // j = 37
        10'sd56, // j = 38
        10'sd55, // j = 39
        10'sd54, // j = 40
        10'sd53, // j = 41
        10'sd53, // j = 42
        10'sd52, // j = 43
        10'sd51, // j = 44
        10'sd50, // j = 45
        10'sd49, // j = 46
        10'sd48, // j = 47
        10'sd47, // j = 48
        10'sd47, // j = 49
        10'sd46, // j = 50
        10'sd45, // j = 51
        10'sd44, // j = 52
        10'sd44 // j = 53
    };
// END GENERATED LOG2 TABLES

    // 正の有限入力を x=2^q*m、1/sqrt(2)<=m<sqrt(2) の形へ正規化する。
    // subnormal入力では先頭の1を検出し、仮数と指数を同じ形式へ揃える。
    wire        x_sign = x[31];
    wire [7:0]  x_exponent = x[30:23];
    wire [22:0] x_fraction = x[22:0];
    wire        x_is_nan = x_exponent == 8'hff && x_fraction != 0;
    wire        x_is_positive_inf = !x_sign && x_exponent == 8'hff
        && x_fraction == 0;
    wire        x_is_zero = {x_exponent, x_fraction} == 31'd0;
    wire        special = x_is_nan || x_is_positive_inf || x_is_zero || x_sign;
    wire [31:0] special_result = x_is_positive_inf ? inf
        : x_is_zero ? neg_inf
        : special ? qnan
        : zero;

    // subnormal仮数の最上位1を固定長のpriority encoderで検出する。
    wire [4:0] leading_index = x_fraction[22] ? 5'd22
        : x_fraction[21] ? 5'd21
        : x_fraction[20] ? 5'd20
        : x_fraction[19] ? 5'd19
        : x_fraction[18] ? 5'd18
        : x_fraction[17] ? 5'd17
        : x_fraction[16] ? 5'd16
        : x_fraction[15] ? 5'd15
        : x_fraction[14] ? 5'd14
        : x_fraction[13] ? 5'd13
        : x_fraction[12] ? 5'd12
        : x_fraction[11] ? 5'd11
        : x_fraction[10] ? 5'd10
        : x_fraction[9]  ? 5'd9
        : x_fraction[8]  ? 5'd8
        : x_fraction[7]  ? 5'd7
        : x_fraction[6]  ? 5'd6
        : x_fraction[5]  ? 5'd5
        : x_fraction[4]  ? 5'd4
        : x_fraction[3]  ? 5'd3
        : x_fraction[2]  ? 5'd2
        : x_fraction[1]  ? 5'd1
        : 5'd0;
    wire [4:0] normalization_shift = 5'd23 - leading_index;
    wire [23:0] subnormal_significand =
        {1'b0, x_fraction} << normalization_shift;
    wire [23:0] significand = x_exponent != 0
        ? {1'b1, x_fraction}
        : subnormal_significand;
    wire signed [9:0] base_exponent = x_exponent != 0
        ? $signed({2'b00, x_exponent}) - 10'sd127
        : $signed({5'b00000, leading_index}) - 10'sd149;
    wire significand_above_sqrt2 = significand >= sqrt2_q23;
    wire [24:0] m_q24_normalized = significand_above_sqrt2
        ? {1'b0, significand}
        : {significand, 1'b0};
    wire signed [9:0] q_normalized = significand_above_sqrt2
        ? base_exponent + 10'sd1
        : base_exponent;
    wire [24:0] m_q24 = special ? 25'd0 : m_q24_normalized;
    wire signed [9:0] q = special ? 10'sd0 : q_normalized;

    // table中心は c=1+j/128。最近傍へ丸めるとd=m-cはsigned 18-bit Q24となる。
    wire signed [25:0] centered_delta =
        $signed({1'b0, m_q24}) - 26'sd16777216;
    wire [25:0] centered_delta_magnitude = centered_delta < 0
        ? $unsigned(-centered_delta)
        : $unsigned(centered_delta);
    wire [25:0] rounded_table_index =
        (centered_delta_magnitude + 26'd65536) >> 17;
    wire signed [6:0] table_index_magnitude =
        $signed(rounded_table_index[6:0]);
    wire signed [6:0] table_index = centered_delta < 0
        ? -table_index_magnitude
        : table_index_magnitude;
    wire signed [25:0] table_offset_q24 =
        $signed({{19{table_index[6]}}, table_index}) <<< 17;
    wire signed [25:0] table_delta_wide_q24 =
        centered_delta - table_offset_q24;
    wire signed [17:0] table_delta_q24 = table_delta_wide_q24[17:0];

    // 配列はj=-37をaddress 0、j=53をaddress 90として格納する。
    wire signed [7:0] table_address_signed =
        $signed({table_index[6], table_index}) + 8'sd37;
    wire [6:0] table_address = table_address_signed[6:0];
    wire signed [34:0] logarithm_q34 =
        $signed(logarithm_table_q34[table_address]);
    wire signed [29:0] coefficient_a_q27 =
        $signed(coefficient_a_table_q27[table_address]);
    wire signed [18:0] coefficient_b_q17 =
        $signed(coefficient_b_table_q17[table_address]);
    wire signed [9:0] coefficient_c_q8 =
        $signed(coefficient_c_table_q8[table_address]);

    // L[c]+d*(A[c]+d*(B[c]+d*C[c]))をmixed precisionで評価する。
    // 各積は絶対値へround-to-nearestのbiasを加えてから次段のQ形式へ縮める。
    wire signed [27:0] c_product_q32 =
        table_delta_q24 * coefficient_c_q8;
    wire [27:0] c_product_magnitude = c_product_q32 < 0
        ? $unsigned(-c_product_q32) : $unsigned(c_product_q32);
    wire [27:0] c_product_biased = c_product_magnitude + 28'd16384;
    wire [12:0] c_term_magnitude_q17 = c_product_biased[27:15];
    wire signed [13:0] c_term_q17 = c_product_q32 < 0
        ? -$signed({1'b0, c_term_magnitude_q17})
        :  $signed({1'b0, c_term_magnitude_q17});

    wire signed [18:0] b_plus_c_q17 = coefficient_b_q17
        + {{5{c_term_q17[13]}}, c_term_q17};
    wire signed [36:0] b_product_q41 = table_delta_q24 * b_plus_c_q17;
    wire [36:0] b_product_magnitude = b_product_q41 < 0
        ? $unsigned(-b_product_q41) : $unsigned(b_product_q41);
    wire [36:0] b_product_biased = b_product_magnitude + 37'd8192;
    wire [22:0] b_term_magnitude_q27 = b_product_biased[36:14];
    wire signed [23:0] b_term_q27 = b_product_q41 < 0
        ? -$signed({1'b0, b_term_magnitude_q27})
        :  $signed({1'b0, b_term_magnitude_q27});

    wire signed [29:0] a_plus_b_q27 = coefficient_a_q27
        + {{6{b_term_q27[23]}}, b_term_q27};
    wire signed [47:0] correction_product_q51 =
        table_delta_q24 * a_plus_b_q27;
    wire [47:0] correction_product_magnitude = correction_product_q51 < 0
        ? $unsigned(-correction_product_q51)
        : $unsigned(correction_product_q51);
    wire [47:0] correction_product_biased =
        correction_product_magnitude + 48'd65536;
    wire [28:0] correction_magnitude_q34 =
        correction_product_biased[45:17];
    wire signed [29:0] correction_general_q34 = correction_product_q51 < 0
        ? -$signed({1'b0, correction_magnitude_q34})
        :  $signed({1'b0, correction_magnitude_q34});

    wire signed [42:0] q_q34 = $signed({{33{q[9]}}, q}) <<< 34;
    wire signed [42:0] value_q34 = q_q34
        + {{8{logarithm_q34[34]}}, logarithm_q34}
        + {{13{correction_general_q34[29]}}, correction_general_q34};
    wire near_unity = !special && q == 0 && table_index == 0;

    // 一般経路はQ34、q=0かつc=1の経路はQ51のままbinary32へ変換する。
    wire [47:0] correction_magnitude = correction_product_q51 < 0
        ? $unsigned(-correction_product_q51)
        : $unsigned(correction_product_q51);
    wire [42:0] general_magnitude = value_q34 < 0
        ? $unsigned(-value_q34)
        : $unsigned(value_q34);
    wire [44:0] magnitude = near_unity
        ? correction_magnitude[44:0]
        : {2'b00, general_magnitude};
    wire result_sign = near_unity ? correction_product_q51[47] : value_q34[42];

    // 非零値の先頭1はbit 23以上、最大でもbit 44なので、
    // 固定長のpriority encoderでその範囲だけを見る。
    wire [5:0] msb_index = magnitude[44] ? 6'd44
        : magnitude[43] ? 6'd43
        : magnitude[42] ? 6'd42
        : magnitude[41] ? 6'd41
        : magnitude[40] ? 6'd40
        : magnitude[39] ? 6'd39
        : magnitude[38] ? 6'd38
        : magnitude[37] ? 6'd37
        : magnitude[36] ? 6'd36
        : magnitude[35] ? 6'd35
        : magnitude[34] ? 6'd34
        : magnitude[33] ? 6'd33
        : magnitude[32] ? 6'd32
        : magnitude[31] ? 6'd31
        : magnitude[30] ? 6'd30
        : magnitude[29] ? 6'd29
        : magnitude[28] ? 6'd28
        : magnitude[27] ? 6'd27
        : magnitude[26] ? 6'd26
        : magnitude[25] ? 6'd25
        : magnitude[24] ? 6'd24
        : magnitude[23] ? 6'd23
        : 6'd0;
    wire [5:0] shift_amount = magnitude == 0
        ? 6'd0
        : msb_index - 6'd23;
    wire [44:0] shifted = magnitude >> shift_amount;
    wire [5:0] sticky_width = shift_amount == 0
        ? 6'd0
        : shift_amount - 6'd1;
    wire [44:0] sticky_mask = (45'd1 << sticky_width) - 45'd1;
    wire guard = shift_amount == 0 ? 1'b0 : magnitude[sticky_width];
    wire sticky = |(magnitude & sticky_mask);
    wire [24:0] significand_unrounded = {1'b0, shifted[23:0]};
    wire round_up = guard & (sticky | significand_unrounded[0]);
    wire [24:0] significand_rounded = significand_unrounded
        + {{24{1'b0}}, round_up};
    wire significand_carry = significand_rounded[24];
    wire [23:0] result_significand = significand_carry
        ? significand_rounded[24:1]
        : significand_rounded[23:0];
    wire signed [10:0] result_exponent_before_carry =
        $signed({5'b00000, msb_index})
        - (near_unity ? 11'sd51 : 11'sd34);
    wire signed [10:0] result_exponent = result_exponent_before_carry
        + $signed({10'b0, significand_carry});
    wire signed [10:0] biased_result_exponent_wide =
        result_exponent + 11'sd127;
    wire [7:0] biased_result_exponent = biased_result_exponent_wide[7:0];
    wire [31:0] finite_result = {
        result_sign,
        biased_result_exponent,
        result_significand[22:0]
    };

    assign result = special ? special_result
        : magnitude == 0 ? zero
        : finite_result;
endmodule
