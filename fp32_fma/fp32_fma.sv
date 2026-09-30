// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0

// 組合せのbinary32積和。積は丸めず、最終出力で指定モードへ一度だけ丸める。
module FP32FMA (
    input  wire [31:0] a,
    input  wire [31:0] b,
    input  wire [31:0] c,
    input  wire [2:0] rounding_mode,
    output wire [31:0] result
);
    localparam [2:0] RNE = 3'b000, RTZ = 3'b001, RDN = 3'b010,
                     RUP = 3'b011, RMM = 3'b100;
    wire round_down = rounding_mode == RDN;
    wire round_up = rounding_mode == RUP;
    wire a_zero = a[30:0] == 31'b0;
    wire b_zero = b[30:0] == 31'b0;
    wire c_zero = c[30:0] == 31'b0;
    wire a_inf = a[30:0] == 31'h7f800000;
    wire b_inf = b[30:0] == 31'h7f800000;
    wire c_inf = c[30:0] == 31'h7f800000;
    wire a_nan = (&a[30:23]) && (|a[22:0]);
    wire b_nan = (&b[30:23]) && (|b[22:0]);
    wire c_nan = (&c[30:23]) && (|c[22:0]);
    wire product_sign = a[31] ^ b[31];
    wire subtract = product_sign ^ c[31];
    wire invalid_operation = (a_zero && b_inf) || (b_zero && a_inf) ||
                             ((a_inf || b_inf) && c_inf && subtract);
    wire nan_result = a_nan || b_nan || c_nan || invalid_operation || rounding_mode > RMM;
    wire inf_result = a_inf || b_inf || c_inf;

    wire [23:0] a_significand = {|a[30:23], a[22:0]};
    wire [23:0] b_significand = {|b[30:23], b[22:0]};
    wire [23:0] c_significand = {|c[30:23], c[22:0]};
    wire signed [9:0] a_exponent = $signed({2'b0, a[30:23] == 8'b0 ? 8'd1 : a[30:23]});
    wire signed [9:0] b_exponent = $signed({2'b0, b[30:23] == 8'b0 ? 8'd1 : b[30:23]});
    wire signed [9:0] c_exponent = $signed({2'b0, c[30:23] == 8'b0 ? 8'd1 : c[30:23]});
    wire signed [9:0] product_exponent = a_exponent + b_exponent - 10'sd127;

    // Mcをbit 75:52に置き、Ep-Ec+26だけ右shiftすると積と格子が一致する。
    wire signed [9:0] alignment_shift = product_exponent - c_exponent + 10'sd26;
    // 距離の下位4 bitは上位の指数計算を経由せず、同じ値を先行生成する。
    wire [3:0] early_shift = a_exponent[3:0] + b_exponent[3:0] + ~c_exponent[3:0] + 4'd12;
    wire [6:0] alignment_control = {alignment_shift[6:4], early_shift};
    wire addend_dominates = !c_zero && (alignment_shift < 10'sd0 || a_zero || b_zero);
    // 加数の右shift。落ちたbitを各段でbit 0へ集約する。
    reg [75:0] shifted_addend;
    reg alignment_lost;
    always_comb begin
        shifted_addend = {c_significand, 52'b0};
        alignment_lost = 1'b0;
        for (integer k = 0; k < 7; k = k + 1) begin
            if (alignment_control[k]) begin
                alignment_lost = |(shifted_addend & ((76'd1 << (1 << k)) - 76'd1));
                shifted_addend = (shifted_addend >> (1 << k)) | {75'b0, alignment_lost};
            end
        end
    end
    wire [75:0] aligned_addend = alignment_shift < 10'sd0 ? 76'b0 :
        |alignment_shift[9:7] ? {75'b0, |c_significand} : shifted_addend;
    // 加数が支配的でも、非zeroの積は方向指定の丸めに影響する。
    // 積と加数が同符号なら絶対値を増やし、逆符号なら減らす隣接値を使う。
    wire adjust_addend = !(a_zero || b_zero) &&
                         ((rounding_mode == RTZ && subtract) ||
                          (round_down && product_sign) || (round_up && !product_sign));
    wire [30:0] adjacent_addend = c[30:0] + (subtract ? 31'h7fffffff : 31'd1);
    wire [31:0] dominant_result = adjust_addend ? {c[31], adjacent_addend} : c;
    wire bypass = nan_result || inf_result || addend_dominates;
    wire [31:0] bypass_value = nan_result ? 32'h7fc00000 :
                              inf_result ? {c_inf ? c[31] : product_sign, 8'hff, 23'b0} : dominant_result;

    // 24×24の積は48 bit。符号反転とcarry-inも同じ積和へ接続する。
    wire [47:0] product = a_significand * b_significand;
    wire [76:0] addend_twos = {1'b0, aligned_addend} ^ {77{subtract}};
    // 積はbit 50以下。下位積和と並列に上位+1の伝播条件を作る。
    wire [51:0] lower_sum = {1'b0, product, 3'b0} +
                           {1'b0, addend_twos[50:0]} + {51'b0, subtract};
    wire [25:0] upper_base = addend_twos[76:51];
    wire [25:0] upper_carry_prefix;
    assign upper_carry_prefix[0] = 1'b1;
    for (genvar j = 1; j < 26; j = j + 1) begin : upper_prefix_bits
        assign upper_carry_prefix[j] = &upper_base[j-1:0];
    end
    // 下位carryが立つ場合だけ、+1で反転する上位bitを切り替える。
    wire [76:0] sum = {upper_base ^ (upper_carry_prefix & {26{lower_sum[51]}}),
                       lower_sum[50:0]};
    wire sum_zero = sum == 77'b0;
    wire sum_sign = sum_zero ? (subtract ? round_down : product_sign) : product_sign ^ sum[76];

    // normal加数の上位距離は整列距離から求める。上位が減算で消える場合は下位を使う。
    wire upper_nonzero = |aligned_addend[75:51];
    wire upper_active = upper_nonzero &&
        !(subtract && lower_sum[51] && aligned_addend[75:51] == 25'd1);
    wire upper_denormal = upper_nonzero && !c_significand[23];
    // +1の伝播範囲外に元の1が残らなければ、先頭距離を1だけ補正する。
    wire upper_step = ~|(aligned_addend[75:51] & ~upper_carry_prefix[24:0]);
    // 上位採用時の距離は0〜25。加算は-1、減算は+1を5 bitで表す。
    wire [4:0] upper_shift_delta = upper_step ? (subtract ? 5'd1 : 5'd31) : 5'd0;
    wire [4:0] upper_shift_carry = alignment_shift[4:0] + upper_shift_delta;
    // 負値は|sum|-1の先頭を使い、絶対値化の+1は最終丸めへ送る。
    // 下位内部50遷移を検出し、carryに依存する境界bit 50を後から選ぶ。
    wire [49:0] leading_input = lower_sum[49:0] ^ lower_sum[50:1];
    reg [6:0] lower_zeros;
    always_comb begin
        lower_zeros = 7'd75;
        for (integer i = 0; i < 50; i = i + 1) begin
            if (leading_input[i]) lower_zeros = 7'(75 - i);
        end
    end
    wire boundary_transition = addend_twos[51] ^ lower_sum[51] ^ lower_sum[50];
    // 距離は76 bit全体の上端基準。境界50／carry51にも同じ符号化を使う。
    wire [6:0] lower_shift = !subtract && lower_sum[51] ? 7'd24 :
                           boundary_transition ? 7'd25 : lower_zeros;
    wire [6:0] leading_zeros = upper_active ?
        {2'b0, (lower_sum[51] ? upper_shift_carry : alignment_shift[4:0])} : lower_shift;
    wire signed [9:0] normalized_exponent = product_exponent + 10'sd26 - $signed({3'b0, leading_zeros});
    // 上位に残るsubnormal加数は固定格子で扱い、指数0/1を丸め後に判定する。
    wire subnormal = upper_denormal || normalized_exponent <= 10'sd0;
    // 仮数24 bitとguard/roundを残す窓を段階ごとに狭める。
    // 左shiftの上限Ep+25は、subnormalで出力の最下位桁を固定するためのbudget。
    wire signed [9:0] shift_budget = product_exponent + 10'sd25;
    wire tiny = shift_budget < 10'sd0;
    wire [6:0] normalize_shift = tiny ? 7'b0 : subnormal ? shift_budget[6:0] : leading_zeros;
    // 生の和をzero-fillでshiftし、狭い出力で反転する。
    // 負値では (|sum| << normalize_shift)-1 となり、強い相殺でも+1を遅延できる。
    wire [75:0] norm64 = normalize_shift[6] ? {sum[11:0], 64'b0} : sum[75:0];
    wire [56:0] norm32 = normalize_shift[5] ? {norm64[43:0], 13'b0} : norm64[75:19];
    wire [40:0] norm16 = normalize_shift[4] ? norm32[40:0] : norm32[56:16];
    wire [32:0] norm8 = normalize_shift[3] ? norm16[32:0] : norm16[40:8];
    wire [28:0] norm4 = normalize_shift[2] ? norm8[28:0] : norm8[32:4];
    wire [26:0] norm2 = normalize_shift[1] ? norm4[26:0] : norm4[28:2];
    wire [25:0] norm1 = normalize_shift[0] ? norm2[25:0] : norm2[26:1];
    wire norm_sticky = (!normalize_shift[5] && |norm64[18:0]) ||
                       (!normalize_shift[4] && |norm32[15:0]) ||
                       (!normalize_shift[3] && |norm16[7:0]) ||
                       (!normalize_shift[2] && |norm8[3:0]) ||
                       (!normalize_shift[1] && |norm4[1:0]) ||
                       (!normalize_shift[0] && norm2[0]);
    // Ep<-25で非zeroの加数はbypass済み。残る積は最小subnormalの半分未満。
    wire [25:0] normalized_word = norm1 ^ {26{sum[76]}};
    // 負値でのbit 0は反転前のsticky。通常のGRS丸めは正値だけへ適用する。
    wire [26:0] grs = tiny ? {26'b0, !sum_zero} : {normalized_word, norm_sticky};
    wire positive_inexact = |grs[2:0];
    wire round_away = (round_down && sum_sign) || (round_up && !sum_sign);
    // 負値のguardより下がall-oneかは、反転前の捨てたbitのORだけで分かる。
    // +1が仮数へ届く場合と、+1後の丸め増分は同時に二度発生しない。
    wire negative_tail_all_one = grs[1] && !norm_sticky;
    wire increment = sum[76] ?
        (rounding_mode == RNE ? grs[2] || (grs[3] && negative_tail_all_one) :
         rounding_mode == RMM ? grs[2] || negative_tail_all_one :
         round_away || (grs[2] && negative_tail_all_one)) :
        ((rounding_mode == RNE && grs[2] && (grs[3] || grs[1] || grs[0])) ||
         (rounding_mode == RMM && grs[2]) || (round_away && positive_inexact));
    wire [24:0] rounded = {1'b0, grs[26:3]} + {24'b0, increment};
    wire [9:0] result_exponent = subnormal ? {9'b0, rounded[23]} :
                                           $unsigned(normalized_exponent) + {9'b0, rounded[24]};
    wire [22:0] result_fraction = rounded[24] ? rounded[23:1] : rounded[22:0];
    wire overflow_to_inf = rounding_mode == RNE || rounding_mode == RMM ||
                           (round_down && sum_sign) || (round_up && !sum_sign);
    wire [31:0] overflow_result = {sum_sign, overflow_to_inf ? 31'h7f800000 : 31'h7f7fffff};
    wire [31:0] finite_result = result_exponent >= 10'd255 ? overflow_result :
                               {sum_sign, result_exponent[7:0], result_fraction};
    assign result = bypass ? bypass_value : sum_zero ? {sum_sign, 31'b0} : finite_result;
endmodule
