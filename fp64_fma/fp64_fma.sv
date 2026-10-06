// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0

// 組合せのbinary64積和。積は丸めず、最終出力で指定モードへ一度だけ丸める。
module FP64FMA (
    input  wire [63:0] a,
    input  wire [63:0] b,
    input  wire [63:0] c,
    input  wire [2:0] rounding_mode,
    output wire [63:0] result
);
    localparam [2:0] RNE = 3'b000, RTZ = 3'b001, RDN = 3'b010,
                     RUP = 3'b011, RMM = 3'b100;
    wire round_down = rounding_mode == RDN;
    wire round_up = rounding_mode == RUP;
    wire a_zero = a[62:0] == 63'b0;
    wire b_zero = b[62:0] == 63'b0;
    wire c_zero = c[62:0] == 63'b0;
    wire a_inf = a[62:0] == 63'h7ff0000000000000;
    wire b_inf = b[62:0] == 63'h7ff0000000000000;
    wire c_inf = c[62:0] == 63'h7ff0000000000000;
    wire a_nan = (&a[62:52]) && (|a[51:0]);
    wire b_nan = (&b[62:52]) && (|b[51:0]);
    wire c_nan = (&c[62:52]) && (|c[51:0]);
    wire product_sign = a[63] ^ b[63];
    wire subtract = product_sign ^ c[63];
    wire invalid_operation = (a_zero && b_inf) || (b_zero && a_inf) ||
                             ((a_inf || b_inf) && c_inf && subtract);
    wire nan_result = a_nan || b_nan || c_nan || invalid_operation || rounding_mode > RMM;
    wire inf_result = a_inf || b_inf || c_inf;

    wire [52:0] a_significand = {|a[62:52], a[51:0]};
    wire [52:0] b_significand = {|b[62:52], b[51:0]};
    wire [52:0] c_significand = {|c[62:52], c[51:0]};
    wire signed [12:0] a_exponent = $signed({2'b0, a[62:52] == 11'b0 ? 11'd1 : a[62:52]});
    wire signed [12:0] b_exponent = $signed({2'b0, b[62:52] == 11'b0 ? 11'd1 : b[62:52]});
    wire signed [12:0] c_exponent = $signed({2'b0, c[62:52] == 11'b0 ? 11'd1 : c[62:52]});
    wire signed [12:0] product_exponent = a_exponent + b_exponent - 13'sd1023;

    // Mcをbit 162:110に置き、Ep-Ec+55だけ右shiftすると積と格子が一致する。
    wire signed [12:0] alignment_shift = product_exponent - c_exponent + 13'sd55;
    // -1023+55を下位4 bitで計算し、加数シフタの小さい段を先行させる。
    wire [3:0] early_shift = a_exponent[3:0] + b_exponent[3:0] + ~c_exponent[3:0] + 4'd9;
    wire [7:0] alignment_control = {alignment_shift[7:4], early_shift};
    wire addend_dominates = !c_zero && (alignment_shift < 13'sd0 || a_zero || b_zero);
    // 加数の右shift。落ちたbitを各段でbit 0へ集約する。
    reg [162:0] shifted_addend;
    reg alignment_lost;
    always_comb begin
        shifted_addend = {c_significand, 110'b0};
        alignment_lost = 1'b0;
        for (integer k = 0; k < 8; k = k + 1) begin
            if (alignment_control[k]) begin
                alignment_lost = |(shifted_addend & ((163'd1 << (1 << k)) - 163'd1));
                shifted_addend = (shifted_addend >> (1 << k)) | {162'b0, alignment_lost};
            end
        end
    end
    wire [162:0] aligned_addend = alignment_shift < 13'sd0 ? 163'b0 :
        |alignment_shift[12:8] ? {162'b0, |c_significand} : shifted_addend;
    // 加数が支配的でも、非zeroの積は方向指定の丸めに影響する。
    wire adjust_addend = !(a_zero || b_zero) &&
                         ((rounding_mode == RTZ && subtract) ||
                          (round_down && product_sign) || (round_up && !product_sign));
    wire [62:0] adjacent_addend = c[62:0] + (subtract ? 63'h7fffffffffffffff : 63'd1);
    wire [63:0] dominant_result = adjust_addend ? {c[63], adjacent_addend} : c;
    wire bypass = nan_result || inf_result || addend_dominates;
    wire [63:0] bypass_value = nan_result ? 64'h7ff8000000000000 :
                              inf_result ? {c_inf ? c[63] : product_sign, 11'h7ff, 52'b0} : dominant_result;

    // 53×53の積を106 bitのまま保持し、符号反転・carry-inとともに下位積和へ接続する。
    wire [105:0] product = a_significand * b_significand;
    wire [163:0] addend_twos = {1'b0, aligned_addend} ^ {164{subtract}};
    // 積はbit 108以下。上位は下位積和を待たずに+1の伝播条件を作る。
    wire [109:0] lower_sum = {1'b0, product, 3'b0} +
                            {1'b0, addend_twos[108:0]} + {109'b0, subtract};
    wire [54:0] upper_base = addend_twos[163:109];
    wire [54:0] upper_carry_prefix;
    assign upper_carry_prefix[0] = 1'b1;
    for (genvar j = 1; j < 55; j = j + 1) begin : upper_prefix_bits
        assign upper_carry_prefix[j] = &upper_base[j-1:0];
    end
    wire [163:0] sum = {upper_base ^ (upper_carry_prefix & {55{lower_sum[109]}}),
                        lower_sum[108:0]};
    wire sum_zero = sum == 164'b0;
    wire sum_sign = sum_zero ? (subtract ? round_down : product_sign) : product_sign ^ sum[163];

    // normal加数の上位距離は整列距離から求め、減算で上位が消える場合は下位を使う。
    wire upper_nonzero = |aligned_addend[162:109];
    wire upper_active = upper_nonzero &&
        !(subtract && lower_sum[109] && aligned_addend[162:109] == 54'd1);
    wire upper_denormal = upper_nonzero && !c_significand[52];
    wire upper_step = ~|(aligned_addend[162:109] & ~upper_carry_prefix[53:0]);
    // 上位採用時の距離は0〜54。加算は-1、減算は+1を6 bitで表す。
    wire [5:0] upper_shift_delta = upper_step ? (subtract ? 6'd1 : 6'd63) : 6'd0;
    wire [5:0] upper_shift_carry = alignment_shift[5:0] + upper_shift_delta;
    // 隣接XORで正値の先頭と、負値の|sum|-1の先頭を共通に検出する。
    wire [107:0] leading_input = lower_sum[107:0] ^ lower_sum[108:1];
    reg [7:0] lower_zeros;
    always_comb begin
        lower_zeros = 8'd162;
        for (integer i = 0; i < 108; i = i + 1) begin
            if (leading_input[i]) lower_zeros = 8'(162 - i);
        end
    end
    wire boundary_transition = addend_twos[109] ^ lower_sum[109] ^ lower_sum[108];
    // 距離は163 bitの上端基準。境界108／carry109も同じ符号化を使う。
    wire [7:0] lower_shift = !subtract && lower_sum[109] ? 8'd53 :
                           boundary_transition ? 8'd54 : lower_zeros;
    wire [7:0] leading_zeros = upper_active ?
        {2'b0, (lower_sum[109] ? upper_shift_carry : alignment_shift[5:0])} : lower_shift;
    wire signed [12:0] normalized_exponent = product_exponent + 13'sd55 - $signed({5'b0, leading_zeros});
    // 上位に残るsubnormal加数は固定格子を使い、指数0/1を丸め後に判定する。
    wire subnormal = upper_denormal || normalized_exponent <= 13'sd0;
    wire signed [12:0] shift_budget = product_exponent + 13'sd54;
    wire tiny = shift_budget < 13'sd0;
    wire [7:0] normalize_shift = tiny ? 8'b0 : subnormal ? shift_budget[7:0] : leading_zeros;
    // 仮数53 bitとguard/roundの保持窓を狭め、不要になった低位桁をstickyへ送る。
    // 生の和をzero-fillでshiftしてから反転し、負値の絶対値化+1は丸めへ遅延する。
    wire [162:0] norm128 = normalize_shift[7] ? {sum[34:0], 128'b0} : sum[162:0];
    wire [117:0] norm64 = normalize_shift[6] ? {norm128[98:0], 19'b0} : norm128[162:45];
    wire [85:0] norm32 = normalize_shift[5] ? norm64[85:0] : norm64[117:32];
    wire [69:0] norm16 = normalize_shift[4] ? norm32[69:0] : norm32[85:16];
    wire [61:0] norm8 = normalize_shift[3] ? norm16[61:0] : norm16[69:8];
    wire [57:0] norm4 = normalize_shift[2] ? norm8[57:0] : norm8[61:4];
    wire [55:0] norm2 = normalize_shift[1] ? norm4[55:0] : norm4[57:2];
    wire [54:0] norm1 = normalize_shift[0] ? norm2[54:0] : norm2[55:1];
    wire norm_sticky = (!normalize_shift[6] && |norm128[44:0]) ||
                       (!normalize_shift[5] && |norm64[31:0]) ||
                       (!normalize_shift[4] && |norm32[15:0]) ||
                       (!normalize_shift[3] && |norm16[7:0]) ||
                       (!normalize_shift[2] && |norm8[3:0]) ||
                       (!normalize_shift[1] && |norm4[1:0]) ||
                       (!normalize_shift[0] && norm2[0]);
    // Ep<-54で非zeroの加数はbypass済み。残る積は最小subnormalの半分未満。
    wire [54:0] normalized_word = norm1 ^ {55{sum[163]}};
    wire [55:0] grs = tiny ? {55'b0, !sum_zero} : {normalized_word, norm_sticky};
    wire positive_inexact = |grs[2:0];
    wire round_away = (round_down && sum_sign) || (round_up && !sum_sign);
    // 負値のguardより下がall-oneかは、反転前の捨てたbitのORで判定する。
    // 絶対値化の+1が仮数へ届く場合と丸め増分は、同時に二度発生しない。
    wire negative_tail_all_one = grs[1] && !norm_sticky;
    wire increment = sum[163] ?
        (rounding_mode == RNE ? grs[2] || (grs[3] && negative_tail_all_one) :
         rounding_mode == RMM ? grs[2] || negative_tail_all_one :
         round_away || (grs[2] && negative_tail_all_one)) :
        ((rounding_mode == RNE && grs[2] && (grs[3] || grs[1] || grs[0])) ||
         (rounding_mode == RMM && grs[2]) || (round_away && positive_inexact));
    wire [53:0] rounded = {1'b0, grs[55:3]} + {53'b0, increment};
    wire [12:0] result_exponent = subnormal ? {12'b0, rounded[52]} :
                                            $unsigned(normalized_exponent) + {12'b0, rounded[53]};
    wire overflow_to_inf = rounding_mode == RNE || rounding_mode == RMM ||
                           (round_down && sum_sign) || (round_up && !sum_sign);
    wire [63:0] overflow_result = {sum_sign, overflow_to_inf ? 63'h7ff0000000000000 : 63'h7fefffffffffffff};
    wire output_overflow = result_exponent >= 13'd2047;
    // 通常値・加数bypass・最大有限値・NaNのfractionを排他的な条件で合成する。
    wire output_finite = !bypass && !sum_zero;
    wire output_regular = output_finite && !output_overflow;
    wire output_maximum = output_finite && output_overflow && !overflow_to_inf;
    wire output_addend = !nan_result && !inf_result && addend_dominates;
    wire [51:0] output_fraction =
        (rounded[51:0] & {52{output_regular}}) |
        (dominant_result[51:0] & {52{output_addend}}) |
        {52{output_maximum}} | {nan_result, 51'b0};
    // 丸めcarry時のfractionは既に0。指数だけ繰り上げ、1 bitシフタは使わない。
    wire [11:0] finite_upper = output_overflow ? overflow_result[63:52] :
                                                {sum_sign, result_exponent[10:0]};
    wire [11:0] output_upper = bypass ? bypass_value[63:52] :
                              sum_zero ? {sum_sign, 11'b0} : finite_upper;
    assign result = {output_upper, output_fraction};
endmodule
