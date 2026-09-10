# Copyright 2026 Ryota Shioya and Toru Koizumi
# SPDX-License-Identifier: Apache-2.0
"""一次近似の係数と、幅・丸め位置を明示した形式共有RTLを生成する。

generate()はRTLと同じ順に、入力分解、expの範囲縮小、形式別の係数表、
共有一次近似、出力丸め、特殊値選択を並べる。数値モデルはstudy.pyを正本とする。
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from study import OPS, Domain, coefficients, linear, residual, width

# (fraction幅, (残差・c0の小数bit数, c1の小数bit数), (exp, recip, rsqrtの区間index幅))
# rsqrtの表だけは、区間indexに指数偶奇の1 bitを加える。
PROFILES = {
    "fp16": (10, (13, 9), (4, 4, 4)),
    "bf16": (7, (9, 5), (2, 3, 2)),
}
TOP = "FP16BF16ExpRecipRsqrtStudy"


def literal(value, bits, signed=False):
    return ("-" if value < 0 else "") + f"{bits}'{'s' if signed else ''}d{abs(value)}"


def extend(signal, bits, target, signed=False):
    if bits == target:
        return signal
    assert bits < target, (signal, bits, target)
    upper = f"{signal}[{bits-1}]" if signed else "1'b0"
    return "{" + "{" + str(target-bits) + "{" + upper + "}}, " + signal + "}"


def grs(signal, bits, shift, retained):
    """定数shiftの保持bit／guard／stickyを連結し、可変幅の加算を作らない。"""
    assert shift > 0
    high_bits = max(0, bits-shift)
    high = f"{signal}[{bits-1}:{shift}]" if high_bits else "1'b0"
    if high_bits > retained:
        high = f"{signal}[{shift+retained-1}:{shift}]"
    elif high_bits < retained:
        high = "{" + f"{retained-high_bits}'d0" + (", " + high if high_bits else "") + "}"
    guard = f"{signal}[{shift-1}]" if shift <= bits else "1'b0"
    sticky = f"(|{signal}[{min(bits,shift-1)-1}:0])" if shift > 1 else "1'b0"
    return "{" + f"{high}, {guard}, {sticky}" + "}"


def generate():
    lines = """// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0
// gen_rtl.pyで生成。FP16／BF16の一次方式を実行時に切り替える。
// is_bf16=0: FP16、1: BF16。op=001: exp、010: recip、100: rsqrt。
// 入出力FTZ、normal結果は最大1 RNE step。特殊値の仕様はREADME.mdを参照。
// 流れ: 入力分解 → 範囲縮小 → 係数選択 → 共有一次近似 → 正規化・丸め → 特殊値選択。
// Qqは整数値を2^qで割って解釈する固定小数点表記。signedの有無は各wireに明示する。
module FP16BF16ExpRecipRsqrtStudy #(
    parameter integer FORMAT_MODE = 0 // 0: 実行時切替、1: FP16専用、2: BF16専用
) (
    input wire [15:0] x,
    input wire [2:0] op,
    input wire is_bf16,
    output wire [15:0] result
);
    // 専用設定ではis_bf16を参照せず、形式依存の枝を合成時に定数化する。
    wire use_bf16 = (FORMAT_MODE == 2) || ((FORMAT_MODE == 0) && is_bf16);

    // 1. 入力形式と演算の分解
    // 指数fieldは8 bitへ揃える。input_eはbiasを除いた指数、parityはその偶奇。
    wire select_exp = op == 3'b001;
    wire select_recip = op == 3'b010;
    wire select_rsqrt = op == 3'b100;
    wire valid_op = select_exp | select_recip | select_rsqrt;
    wire [7:0] exponent = use_bf16 ? x[14:7] : {3'd0, x[14:10]};
    wire exponent_zero = ~|exponent;
    wire exponent_all_ones = use_bf16 ? (&exponent) : (&exponent[4:0]);
    wire fraction_zero = use_bf16 ? (~|x[6:0]) : (~|x[9:0]);
    wire signed [8:0] input_e =
        $signed({1'b0, exponent}) - (use_bf16 ? 9'sd127 : 9'sd15);
    wire parity = input_e[0];

    // 2. expの範囲縮小: z=x*log2(e)、exp(x)=2^floor(z)*2^frac(z)
    // 仮数をQ10へ揃え、Q14のlog2(e)を掛ける。exp_productはQ24。
    // BF16仮数の3 bit左詰めは配線で行い、11×15の定数乗算器を共有する。
    wire [10:0] mantissa = use_bf16 ? {1'b1, x[6:0], 3'd0} : {1'b1, x[9:0]};
    wire [25:0] exp_product = mantissa * 15'd23637;
    // 指数による倍率を反映し、zをFP16ではQ13、BF16ではQ9へ丸める。
    // shift量はFP16: 26-指数field、BF16: 142-指数field。減算せず直接decodeする。
    // exp_grs={保持する21 bit, guard, sticky}。各枝では配線だけを選択する。
    wire [22:0] exp_grs;""".splitlines()
    # |x|<128の有効範囲では右shiftだけ。保持bit・guard・stickyを選んで一度丸める。
    expr = "23'd0"
    for shift in range(5, 27):
        selected = f"(use_bf16 ? (x[14:7] == 8'd{142-shift}) : (x[14:10] == 5'd{26-shift}))"
        expr = f"{selected} ?\n            {grs('exp_product',26,shift,21)} :\n        " + expr
    lines += ["    assign exp_grs =\n        " + expr + ";"]
    lines += """    // RNEの繰上げ条件はguard && (sticky || 保持部LSB)。tieは偶数側へ丸める。
    wire [20:0] exp_magnitude =
        exp_grs[22:2] + {20'd0, (exp_grs[1] & (exp_grs[0] | exp_grs[2]))};
    wire signed [21:0] exp_z =
        x[15] ? -$signed({1'b0, exp_magnitude}) : $signed({1'b0, exp_magnitude});

    // 近似に使うtの下位bitは、根系ではm-1、expではfrac(z)を表す。
    // 有効な小数部はFP16: t[12:0] (Q13)、BF16: t[8:0] (Q9)。
    // 負のexp_zも下位bitがfrac(z)、上位bitがfloor(z)を表す。
    wire [12:0] root_t = use_bf16 ? {4'd0, x[6:0], 2'd0} : {x[9:0], 3'd0};
    wire [12:0] t = select_exp ? exp_z[12:0] : root_t;

    // 3. 区間中心からの残差dと係数c0・c1を選ぶ
    // 区間内の下位bitのMSB反転は「下位bit値-区間幅/2」のsigned表現になる。
    // rsqrtの表はparity=0が前半、parity=1が後半。""".splitlines()
    for name, (fraction_bits, coefficient_q, index_widths) in PROFILES.items():
        value_q, slope_q = coefficient_q
        quantized = {}
        lines += ["", f"    // {name.upper()}: d・c0はQ{value_q}、c1はQ{slope_q}。"]
        for op, index_bits in zip(OPS, index_widths):
            prefix = f"{name}_{op}"
            ideal = coefficients(op, index_bits)
            quantized[op] = [np.rint(ideal[:, i] * (1 << q)).astype(np.int64)
                             for i, q in enumerate(coefficient_q)]
            domain = Domain(fraction_bits, op, np.zeros(65536, dtype=np.int64))
            residual_values, _, _ = residual(domain, index_bits, value_q)
            assert width(residual_values, True) <= 9
            residual_bits = value_q - index_bits
            index = f"t[{value_q-1}:{value_q-index_bits}]"
            if op == "rsqrt":
                index = "{parity, " + index + "}"
            lines += [f"    // {op}: {1 << index_bits}区間" +
                      ("×指数偶奇2通り。" if op == "rsqrt" else "。"),
                      f"    wire [{index_bits+(op == 'rsqrt')-1}:0] {prefix}_index = {index};",
                      f"    wire signed [{residual_bits-1}:0] {prefix}_d = "
                      f"{{~t[{residual_bits-1}], t[{residual_bits-2}:0]}};"]
            for i, values in enumerate(quantized[op]):
                bits = width(values, i == 1)
                assert bits <= (14 if i == 0 else 11)
                sign = "signed " if i == 1 else ""
                lines += [f"    localparam logic {sign}[{bits-1}:0] "
                          f"{prefix.upper()}_C{i} [0:{len(values)-1}] = '{{"]
                # 4要素ずつ表示し、元のtable indexをコメントで追えるようにする。
                for start in range(0, len(values), 4):
                    end = min(start + 4, len(values))
                    entries = ", ".join(literal(int(v), bits, i == 1) for v in values[start:end])
                    comma = "," if end < len(values) else ""
                    lines += [f"        {entries}{comma} // index {start}..{end-1}"]
                lines += ["    };",
                          f"    wire {sign}[{bits-1}:0] {prefix}_c{i} = "
                          f"{prefix.upper()}_C{i}[{prefix}_index];"]
            lines += [""]
        residuals = [f"$signed({extend(name+'_'+op+'_d',value_q-b,9,True)})"
                     for op, b in zip(OPS, index_widths)]
        lines += [f"    // {name.upper()}内で演算を選択し、共有カーネルの幅へ明示的に拡張する。",
                  f"    wire signed [8:0] {name}_d =",
                  f"        select_exp   ? {residuals[0]} :",
                  f"        select_recip ? {residuals[1]} :",
                  f"                       {residuals[2]};"]
        for i, w in enumerate((14, 11)):
            values = [extend(f"{name}_{op}_c{i}", width(quantized[op][i], i == 1), w, i == 1)
                      for op in OPS]
            if i == 1:
                values = [f"$signed({v})" for v in values]
            sign = "signed " if i == 1 else ""
            lines += [f"    wire {sign}[{w-1}:0] {name}_c{i} =",
                      f"        select_exp   ? {values[0]} :",
                      f"        select_recip ? {values[1]} :",
                      f"                       {values[2]};"]
    lines += """
    // 4. 一つの9×11乗算器で、一次近似y=c0+RNE(d*c1)を計算する
    // 小数点位置は形式ごとに維持し、符号拡張だけで共有乗算器へ渡す。
    wire signed [8:0] d = use_bf16 ? bf16_d : fp16_d;
    wire [13:0] c0 = use_bf16 ? bf16_c0 : fp16_c0;
    wire signed [10:0] c1 = use_bf16 ? bf16_c1 : fp16_c1;
    wire signed [19:0] product = d * c1;
    // 積はFP16: Q22、BF16: Q14。9／5 bit右へRNEしてc0と同じQ13／Q9に戻す。
    // signedの上位sliceは負の積を負方向へ切り下げる。そこへRNEの1 bitを加える。
    wire product_round = use_bf16 ? (product[4] & ((|product[3:0]) | product[5]))
                                : (product[8] & ((|product[7:0]) | product[9]));
    wire signed [15:0] product_high = use_bf16 ? $signed({product[19], product[19:5]})
                                            : $signed({{5{product[19]}}, product[19:9]});
    wire signed [15:0] correction = product_high + $signed({15'd0, product_round});
    wire signed [15:0] polynomial = $signed({2'd0, c0}) + correction;
    // recip(m=1)、rsqrt(m=1かつ偶数指数)は近似せず、厳密な1を選択する。
    wire exact_root = !select_exp & fraction_zero & (select_recip | !parity);
    wire [14:0] y = exact_root ? (use_bf16 ? 15'd512 : 15'd8192) : polynomial[14:0];

    // 5. 正規化、指数復元、出力形式へのRNE
    // yはQ13／Q9。到達するbinadeは[0.5,1)、[1,2)、[2,4)の三つだけ。
    wire y_ge_two = use_bf16 ? y[10] : y[14];
    wire y_ge_one = use_bf16 ? y[9] : y[13];
    wire signed [2:0] normalization = y_ge_two ? 3'sd1 : y_ge_one ? 3'sd0 : -3'sd1;
    wire signed [8:0] exp_scale = use_bf16 ? $signed(exp_z[17:9]) : $signed(exp_z[21:13]);
    // exp: floor(z)、recip: -e、rsqrt: -floor(e/2)を復元する。
    wire signed [8:0] scale = select_exp ? exp_scale : select_recip ? -input_e : -(input_e >>> 1);
    wire signed [9:0] biased_before = $signed({scale[8], scale}) + (use_bf16 ? 10'sd127 : 10'sd15)
                                   + $signed({{7{normalization[2]}}, normalization});
    // min normal直下も一度丸め、min normalへ繰り上がらなかった出力だけFTZにする。
    wire near_underflow = biased_before == 10'sd0;
    wire signed [2:0] pack_adjust = normalization + $signed({2'd0, near_underflow});""".splitlines()
    # 保持部(f+1 bit)とguard・stickyを選ぶ。丸め加算そのものは形式間で共有する。
    for name, (f, (q, _), _) in PROFILES.items():
        expr = grs("y", q+2, q-f+2, f+1)
        for adjustment in (1, 0, -1):
            expr = f"(pack_adjust == {literal(adjustment,3,True)}) ? {grs('y',q+2,q-f+adjustment,f+1)} :\n        " + expr
        lines += [f"    wire [{f+2}:0] {name}_pack_grs = {expr};"]
    lines += """    // pack_grs[12:2]が保持部、[1]がguard、[0]がsticky。
    wire [12:0] pack_grs = use_bf16 ? {3'd0, bf16_pack_grs} : fp16_pack_grs;
    wire [11:0] packed_m = {1'b0, pack_grs[12:2]} + {11'd0, (pack_grs[1] & (pack_grs[0] | pack_grs[2]))};
    wire pack_carry = use_bf16 ? packed_m[8] : packed_m[11];
    wire signed [9:0] packed_e = (near_underflow ? 10'sd1 : biased_before) + $signed({9'd0, pack_carry});
    wire [9:0] packed_fraction = use_bf16 ? {3'd0, (pack_carry ? packed_m[7:1] : packed_m[6:0])}
                                       : (pack_carry ? packed_m[10:1] : packed_m[9:0]);
    // 正のInf: BF16=0x7f80、FP16=0x7c00。qNaN: BF16=0x7fc0、FP16=0x7e00。
    wire [14:0] inf = use_bf16 ? 15'd32640 : 15'd31744;
    wire [15:0] nan = use_bf16 ? 16'd32704 : 16'd32256;
    wire [14:0] normal_payload = use_bf16 ? {packed_e[7:0], packed_fraction[6:0]} : {packed_e[4:0], packed_fraction};
    wire [14:0] finite_payload = (biased_before < 10'sd0 || packed_m < (use_bf16 ? 12'd128 : 12'd1024)) ? 15'd0
                              : (packed_e >= (use_bf16 ? 10'sd255 : 10'sd31)) ? inf : normal_payload;

    // 6. 特殊値と無効opの選択（近似結果より優先する）
    // expの|x|>=128は両形式ともoverflow／FTZとなり、近似経路を使わない。
    wire is_nan = exponent_all_ones & !fraction_zero;
    wire negative_rsqrt = select_rsqrt & x[15] & !exponent_zero;
    wire exp_large = input_e >= 9'sd7;
    // exp(±0)=1: BF16=0x3f80、FP16=0x3c00。
    wire [15:0] exp_result = exponent_zero ? (use_bf16 ? 16'd16256 : 16'd15360)
                           : exp_large ? (x[15] ? 16'd0 : {1'b0, inf}) : {1'b0, finite_payload};
    wire [15:0] root_result = exponent_zero ? {x[15], inf}
                            : exponent_all_ones ? {(select_recip & x[15]), 15'd0}
                            : {(select_recip & x[15]), finite_payload};
    assign result = (!valid_op | is_nan | negative_rsqrt) ? nan : select_exp ? exp_result : root_result;
endmodule
""".splitlines()
    return "\n".join(lines) + "\n"


def vectors(name, refs):
    f, qs, bs = PROFILES[name]
    outputs, metrics = [], []
    for oi, (op, b) in enumerate(zip(OPS, bs)):
        domain = Domain(f, op, refs[0 if f == 10 else 1, oi])
        out = linear(domain, b, *qs)
        metric = domain.metrics(out)
        assert metric["violations"] == metric["monotonic"] == 0, (name, op, metric)
        outputs.append(out)
        metrics.append(metric)
    data = np.array(outputs, dtype="<u2").tobytes()
    Path(f"build/{name}.bin").write_bytes(data)
    Path(f"build/{name}.json").write_text(json.dumps({"profile": PROFILES[name], "metrics": metrics,
        "vectors_sha256": hashlib.sha256(data).hexdigest()}, indent=2)+"\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--vectors", action="store_true")
    args = parser.parse_args()
    Path("rtl").mkdir(exist_ok=True)
    text = generate()
    path = Path("rtl/fp16.sv")
    if args.check:
        assert path.read_text() == text, path
    else:
        path.write_text(text)
    if args.vectors:
        refs = np.fromfile("build/reference.bin", dtype="<u2").reshape(2, 3, 65536)
        for name in PROFILES:
            vectors(name, refs)
    print("RTL generation check: PASS" if args.check else "RTL generation: PASS")


if __name__ == "__main__":
    main()
