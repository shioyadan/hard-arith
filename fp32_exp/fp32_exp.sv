// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0

// IEEE 754 binary32 の自然指数関数 e^x を求める組合せ回路。
// * 丸め方式：faithful rounding （無限精度値を挟む二つの binary32 値のどちらかを返す）
// * 単調性：保証される（この関数は非 NaN 入力に対して単調非減少となる）
// * 精度：normal <0.971 ULP、subnormal <1.0 ULP（全 2^32 入力の検証に基づく）
// 例外フラグ・NaN のペイロード・動的丸めモード指定は非対応。
// expf(NaN) は canonical qNaN を返す。
// おおよその計算アルゴリズム：
// 1. x = (q + j/64) ln2 + r となるような q, j, r を求め、
// 2. e^x = 2^q * (Table[j] + Coeff[j] * (r + r^2/2)) を計算する
module FP32Exp(x, result);
    input  wire[31:0] x;
    output wire[31:0] result;

    localparam logic[31:0] zero = 32'h00000000;
    localparam logic[31:0] one  = 32'h3f800000;
    localparam logic[31:0] inf  = 32'h7f800000;
    localparam logic[31:0] qnan = 32'h7fc00000;

    // テーブル値は、最終結果の誤差が可能な限り正負バランスするように選択した。
    // 補正が全体的に正なのは、近似多項式と積の切り捨てによる下向きバイアスに加え、
    // 最終四捨五入の加算をテーブルにあらかじめ織り込んでいるためである。
    // 多くの経路では、最終四捨五入の織り込み分は +4 に相当する。
    // faithful 性・単調性・回路の単純さを優先して誤差バランスを崩した行は次の通り。
    // * j =  0 : バランスが良いのは r >= 0 では +5.00、r < 0 では +3.00 （e^x の指数部が 1 小さくて四捨五入の織り込みが +2 になるため）だが、場合分けなしに全域のバランスを良くする +4.00 を選択した。
    // * j =  1 : バランスが良いのは +4.38 だが、テーブル境界の非単調性を解消できる +5.38 を選択した。
    // * j =  5 : バランスが良いのは +4.29 だが、3 入力で faithful 違反になるのを救える +5.29 を選択した。
    // * j =  9 : バランスが良いのは +5.14 だが、Coeff が RNE 境界をまたいで計算が煩雑になるのを回避できる +4.14 を選択した。
    // * j = 13 : バランスが良いのは +4.53 だが、テーブル境界の非単調性を解消できる +5.53 を選択した。
    // * j = 53 : バランスが良いのは +5.41 だが、2 入力で faithful 違反になるのを救える +6.41 を選択した。
    // * j = 60 : バランスが良いのは +5.34 だが、x = 0x1.5ff81ap+6 で faithful 違反になるのを救える +6.34 を選択した。
    // * j = 63 : バランス以前に、+6.60 では x < 0 の 6 入力で、+5.60 では x > 0 の 16 入力で、それぞれ faithful 違反になる。したがって、x の符号に応じた場合分けが別途必要。
    localparam logic [26:0] exp2_table_q26 [0:63] = '{
        27'h4000004, // 2^( 0/64)*2^26 + 4.00
        27'h40b2695, // 2^( 1/64)*2^26 + 5.38
        27'h4166c3a, // 2^( 2/64)*2^26 + 5.23
        27'h421d14b, // 2^( 3/64)*2^26 + 4.89
        27'h42d5620, // 2^( 4/64)*2^26 + 4.76
        27'h438fb12, // 2^( 5/64)*2^26 + 5.29
        27'h444c079, // 2^( 6/64)*2^26 + 4.98
        27'h450a6b0, // 2^( 7/64)*2^26 + 4.33
        27'h45cae14, // 2^( 8/64)*2^26 + 4.88
        27'h468d6ff, // 2^( 9/64)*2^26 + 4.14
        27'h47521d1, // 2^(10/64)*2^26 + 4.65
        27'h4818ee7, // 2^(11/64)*2^26 + 4.90
        27'h48e1ea0, // 2^(12/64)*2^26 + 4.39
        27'h49ad15f, // 2^(13/64)*2^26 + 5.53
        27'h4a7a782, // 2^(14/64)*2^26 + 4.72
        27'h4b4a16f, // 2^(15/64)*2^26 + 5.28
        27'h4c1bf87, // 2^(16/64)*2^26 + 4.45
        27'h4cf0231, // 2^(17/64)*2^26 + 4.40
        27'h4dc69d3, // 2^(18/64)*2^26 + 5.19
        27'h4e9f6d2, // 2^(19/64)*2^26 + 4.78
        27'h4f7a998, // 2^(20/64)*2^26 + 4.98
        27'h505828d, // 2^(21/64)*2^26 + 4.51
        27'h513821d, // 2^(22/64)*2^26 + 4.90
        27'h521a8b3, // 2^(23/64)*2^26 + 5.56
        27'h52ff6bb, // 2^(24/64)*2^26 + 5.70
        27'h53e6ca3, // 2^(25/64)*2^26 + 5.35
        27'h54d0adb, // 2^(26/64)*2^26 + 5.35
        27'h55bd1d3, // 2^(27/64)*2^26 + 5.32
        27'h56ac1fc, // 2^(28/64)*2^26 + 4.68
        27'h579dbca, // 2^(29/64)*2^26 + 4.58
        27'h5891fb1, // 2^(30/64)*2^26 + 4.94
        27'h5988e25, // 2^(31/64)*2^26 + 4.42
        27'h5a8279f, // 2^(32/64)*2^26 + 5.38
        27'h5b7ec95, // 2^(33/64)*2^26 + 5.90
        27'h5c7dd7f, // 2^(34/64)*2^26 + 4.77
        27'h5d7fadb, // 2^(35/64)*2^26 + 5.44
        27'h5e84522, // 2^(36/64)*2^26 + 5.02
        27'h5f8bcd3, // 2^(37/64)*2^26 + 5.30
        27'h609626c, // 2^(38/64)*2^26 + 5.67
        27'h61a366c, // 2^(39/64)*2^26 + 5.18
        27'h62b3956, // 2^(40/64)*2^26 + 5.46
        27'h63c6bab, // 2^(41/64)*2^26 + 4.73
        27'h64dcdf1, // 2^(42/64)*2^26 + 4.80
        27'h65f60ae, // 2^(43/64)*2^26 + 6.03
        27'h6712466, // 2^(44/64)*2^26 + 5.34
        27'h68319a4, // 2^(45/64)*2^26 + 5.16
        27'h69540f2, // 2^(46/64)*2^26 + 5.44
        27'h6a79adb, // 2^(47/64)*2^26 + 5.63
        27'h6ba27ec, // 2^(48/64)*2^26 + 5.66
        27'h6cce8b4, // 2^(49/64)*2^26 + 5.92
        27'h6dfddc2, // 2^(50/64)*2^26 + 5.25
        27'h6f307a9, // 2^(51/64)*2^26 + 4.93
        27'h70666fd, // 2^(52/64)*2^26 + 5.62
        27'h719fc52, // 2^(53/64)*2^26 + 6.41
        27'h72dc83d, // 2^(54/64)*2^26 + 5.77
        27'h741cb58, // 2^(55/64)*2^26 + 5.49
        27'h756063d, // 2^(56/64)*2^26 + 5.75
        27'h76a7986, // 2^(57/64)*2^26 + 5.04
        27'h77f25d3, // 2^(58/64)*2^26 + 6.13
        27'h7940bbf, // 2^(59/64)*2^26 + 5.11
        27'h7a92bef, // 2^(60/64)*2^26 + 6.34
        27'h7be8701, // 2^(61/64)*2^26 + 5.40
        27'h7d41d9c, // 2^(62/64)*2^26 + 5.14
        27'h7e9f067  // 2^(63/64)*2^26 + 6.60
    };

    // 一次項以降の係数をテーブル値から半規則的な計算で作る際に追加で必要となる情報。
    localparam logic[63:0] coefficient_up_mask   = 64'h7e9d67157815e428;
    localparam logic[63:0] coefficient_bit5_mask = 64'h82f64e5e3b0d227c;

    // 入力の分解
    wire       x_sign = x[31];
    wire [7:0] x_expo = x[30:23];
    wire[22:0] x_mant = x[22:0];
    wire[23:0] x_sig  = { 1'b1, x_mant };
    wire       in_range = x_expo >= 8'd102 & x_expo < 8'd134;

    // x = (q + j/64) ln2 + r なる q, j, r を求めるためには
    // n = round(x * 64/ln2) を求め、q = floor(n/64), j = n mod 64 とすればよい。
    // 実際には |r| ~ ln2/128 付近で厳密に絶対値最小の r を選択する必要はないため、
    // n は厳密な最近傍整数と異なっても良い。よって引数還元 (argument reduction) は
    // x_sig 側と inv_ln2_64 側の双方の下位ビットを削った小さい乗算器で行う。
    // x_sig の下位 6 bit を単に切り捨てると偏りすぎるので、区間中央に相当する
    // 6'b100000 で代表させる区間中央量子化を使っている。
    localparam logic[14:0] inv_ln2_64_q8 = 15'h5c55; // 64/ln2 = 0x5c.551d9...p+0
    wire[33:0] index_product   = { x_sig[23:6], 1'b1 } * inv_ln2_64_q8;
    wire [4:0] reduction_shift = 5'd5 - x_expo[4:0]; // in_range であれば 133 - x_expo と同じ
    wire[14:0] index_window    = index_product[33:19] >> reduction_shift;
    wire[13:0] n_abs           = index_window[14:1] + { 13'b0, index_window[0] }; // 四捨五入
    wire signed[14:0] n        = x_sign ? -$signed({ 1'b0, n_abs }) : $signed({ 1'b0, n_abs });
    wire signed [8:0] q        = n[14:6];
    wire        [5:0] j        = n[5:0];

    // s=|x|-n_abs*ln2/64 を signed Q28 で求める（1 bit 下の位まで計算してから切り落とす）。
    // 回路を小さくするために以下の二つの非自明な最適化を使っている。
    //
    // 1. 乗算器の下を削る。普通に ln2/64 を掛けるならば、精度上は Q35 の定数 0x162e42ff
    // を掛ける必要がある。というのも、この定数の誤差は n_abs 倍されて最終結果に影響を
    // 及ぼすからである。ここでは 0x162e4300 - 0x1 を掛けるとみなした（部分的に Radix-2
    // Booth エンコーディングした）上で、下 6 bit を計算しない近似乗算器を使っている。
    // 省略される 6 bit は負の積項なので、これは単なるビット切り捨てではなく近似であり、
    // 合成系はこの項を自動では無視できない。Yosys による仮評価では、この近似で小さくなった。
    //
    // 2. 乗算器の上も削る。n_abs の取り方から上位は必ずキャンセルするため、
    // 切り落とす前の Q29 残差 S は符号付き 23 bit に収まる。
    // したがって mod 2^23 で計算すればよいが、ここではさらに攻めて mod 2^22 で
    // 計算した後に S の符号ビットを n_abs の丸め方向 (guard bit) から復元する。
    // x * 64/ln2 の下位ビットを省略したので guard bit そのものとは食い違い、
    // 単純な復元はできないが、次の性質より mod 2^22 の上 2 bit を見れば判別可能。
    // * S は最小でも -ln2/128 * 2^29 > -3*2^20 程度なので、
    //   S < 0 では mod 2^22 の上 2 bit は 00 にならない
    // * 逆に S >= 0 でも guard が 1 ならば S < 2^20 となり、
    //   mod 2^22 の上 2 bit は 00 以外にならない
    localparam logic[20:0] ln2_by_64_q27 = 21'h162e43; // ln2/64 = 0x1.62e42fefa...p-7
    wire[35:0] x_q29           = { x_sig, 12'b0 } >> reduction_shift;
    wire[19:0] ln2_product_q27 = n_abs * ln2_by_64_q27[19:0];
    wire[21:0] s_low           = x_q29[21:0] + { 14'b0, n_abs[13:6] } - { ln2_product_q27, 2'b0 };
    wire       s_sign          = index_window[0] & (s_low[21:20] != 2'b00);
    wire signed[21:0] s        = { s_sign, s_low[21:1] };
    // ln2_by_64_q35 での乗算を近似しないなら以下になる。
    // localparam logic[28:0] ln2_by_64_q35 = 29'h162e42ff; // ln2/64 = 0x1.62e42fefa...p-7
    // wire[35:0] x_q29            = { x_sig, 12'b0 } >> reduction_shift;
    // wire[28:0] ln2_product_q35  = n_abs * ln2_by_64_q35;
    // wire signed[22:0] s_q29     = x_q29[22:0] - ln2_product_q35[28:6];
    // wire signed[21:0] s         = s_q29[22:1];

    // exp(r)-1 を r+r^2/2 で近似し、signed Q27 で求める（1 bit 下の位まで計算してから切り落とす）。
    // r は x が正なら s、負なら -s である。
    // 二の補数化は高価なので、安価な一の補数化で代用している（二か所）。
    // 自乗入力は 14 bit あれば、同一 (q, j) 区間の全域で polynomial が x に対して単調非減少になる。
    // ただし、この乗算器の幅広化は面積に無視できない影響を与える。単調性を捨てていいなら、
    // 現在のテーブル・係数のまま自乗入力を 11 bit まで削減した構成でも faithful を守れる。
    wire       [13:0] square_operand = s[21] ? ~s[20:7] : s[20:7];
    wire       [27:0] square_product = square_operand * square_operand;
    wire signed[21:0] linear_r_q28   = x_sign ? ~s[21:0] : s[21:0];
    wire signed[21:0] polynomial_q28 = linear_r_q28 + $signed({ 9'b0, square_product[27:15] });
    wire signed[20:0] polynomial     = polynomial_q28[21:1];

    // Table[j] の生成。j = 63 の時だけ x の符号に応じた修正を加えることで、faithful を守る。
    wire       table_lsb_down  = x_sign & (j == 6'd63);
    wire[26:0] table_q26       = { exp2_table_q26[j][26:1], exp2_table_q26[j][0] & ~table_lsb_down };

    // Coeff[j] の生成。r^3/6 の打切り誤差を一次項で補償することを意図した係数調整である。
    // Table[j]/2^9 * 0x1.00005p+0 程度にする必要がある
    // （x * 64/ln2 の大胆な近似により |r| > ln2/128 となりうる点に注意）。
    // 実際には faithful を守れるような総合的な選択を行い、floor(Table[j]/2^9) + eps[j] とした。
    // eps[j] は行ごとに 1 または 2 を適切に選べば faithful を達成できる。
    // 単に RNE(Table[j]/2^9 + 1) とするだけでは、j = 46 および j = 52 で faithful を守れない。
    // j = 4 で eps[j] を 0 にしているのは、単調性を守るためであり、1 でも faithful は守られる。
    // Coeff[j] の上位ビットは Table[j] の上位ビットと同じ、
    // Coeff[j] の下位ビットは上記の半規則的な計算で作れる。
    // Yosys による仮評価では、下位ビットを全部テーブルに記憶したり全幅の加算器を持ったりする
    // 方式より、計算に与える種のみを記憶して 5 bit 加算器を使うこの方式が小さかった。
    wire       coefficient_nonzero = j != 6'd4;
    wire       coefficient_up      = coefficient_up_mask[j];
    wire [1:0] coefficient_epsilon = { coefficient_up, coefficient_nonzero & ~coefficient_up };
    wire [4:0] coefficient_low     = table_q26[13:9] + { 3'b0, coefficient_epsilon };
    wire[17:0] coefficient         = { table_q26[26:15], coefficient_bit5_mask[j], coefficient_low };

    // Table[j] + Coeff[j] * (r + r^2/2) を Q24 で求める（2 bit 下の位まで計算してから切り落とす）。
    wire signed[18:0] table_coefficient  = $signed({ 1'b0, coefficient });
    wire signed[38:0] correction_product = table_coefficient * polynomial; // u18 * s21 -> s39
    wire signed[20:0] correction         = correction_product[38:18];
    wire       [26:0] correction_wide    = { { 6{correction[20]} }, correction };
    wire       [26:0] exp_mant_q26       = table_q26 + correction_wide;
    wire       [24:0] exp_mant           = exp_mant_q26[26:2];

    // 正規化および最終丸め。正規化は高々 1 bit の調整のみ。
    // 丸めは切り捨てで問題ないようにここまでの計算手順が工夫されている。
    // 最終結果の指数部が 1 小さくなるのは、j = 0, r < 0 の時のみ。
    // j = 0, r < 0 であっても、丸められた結果仮数部が 1.0 になって指数部が
    // そのままのこともあるため、計算結果を見た上で正規化する。
    wire signed [8:0] result_expo = exp_mant[24] ? q : q - 9'sd1;
    wire[22:0] normal_mant        = exp_mant[24] ? exp_mant[23:1] : exp_mant[22:0];
    // result_expo は最小で -185 なので、シフト量は 6 bit で表せば十分。
    wire[22:0] subnormal_mant     = { 1'b1, normal_mant[22:1] } >> 6'(-9'sd127 - result_expo);
    wire       result_is_normal   = result_expo >= -9'sd126;
    wire [7:0] biased_expo        = result_expo[7:0] + 8'd127;
    // normal では四捨五入の +0.5 をテーブルに織り込み済みなので、下位ビットを捨てるだけでよい。
    // subnormal では右シフトで追い出された部分を切り捨てるだけで faithful になる。
    // ただしこの右シフト切り捨ては、最終結果が下向きに丸まりがちというバイアスを乗せてしまう。
    wire[30:0] finite_payload = result_is_normal ? { biased_expo, normal_mant }
                                                 : { 8'b0, subnormal_mant };

    // 特殊値、範囲外、overflow、underflow の処理
    wire       x_is_nan            = x_expo == 8'hff & x_mant != 0;
    wire       result_is_inf       = result_expo > 9'sd127;
    wire[31:0] in_range_result     = result_is_inf ? inf : { 1'b0, finite_payload };
    wire[31:0] limit_result        = x_sign ? zero : inf;
    wire[31:0] out_of_range_result = x_is_nan        ? qnan :
                                     x_expo < 8'd102 ? one : limit_result;

    assign result = in_range ? in_range_result : out_of_range_result;
endmodule
