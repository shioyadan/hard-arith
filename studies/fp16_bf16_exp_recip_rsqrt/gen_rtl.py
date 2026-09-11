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

# (fraction幅, (範囲縮小値・c0の小数bit数, c1の小数bit数), (exp, recip, rsqrtの区間index幅))
# rsqrtの表だけは、区間indexに指数偶奇の1 bitを加える。
PROFILES = {
    "fp16": (10, (13, 7), (4, 4, 4)),
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
// 入出力subnormal対応を合成時に選択。有限非zero結果は最大1 RNE step。
// 流れ: 入力分解 → 範囲縮小 → 係数選択 → 共有一次近似 → 正規化・丸め → 特殊値選択。
// Qqは整数値を2^qで割って解釈する固定小数点表記。signedの有無は各wireに明示する。
module FP16BF16ExpRecipRsqrtStudy #(
    parameter integer FORMAT_MODE = 0, // 0: 実行時切替、1: FP16専用、2: BF16専用
    parameter bit SUPPORT_SUBNORMAL = 1'b1
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
    // 根系だけ入力subnormalを正規化する。BF16の7 bitも上詰めで10 bitへそろえる。
    wire [9:0] input_fraction = use_bf16 ? {x[6:0], 3'd0} : x[9:0];
    wire input_subnormal = SUPPORT_SUBNORMAL & exponent_zero & !fraction_zero;
    wire input_zero = exponent_zero & (!SUPPORT_SUBNORMAL | fraction_zero);
    wire [3:0] leading_shift =
        input_fraction[9] ? 4'd1 : input_fraction[8] ? 4'd2 :
        input_fraction[7] ? 4'd3 : input_fraction[6] ? 4'd4 :
        input_fraction[5] ? 4'd5 : input_fraction[4] ? 4'd6 :
        input_fraction[3] ? 4'd7 : input_fraction[2] ? 4'd8 :
        input_fraction[1] ? 4'd9 : 4'd10;
    // 左shiftで暗黙の1を落とし、小数部だけを既存の近似格子へ渡す。
    wire [9:0] root_fraction = input_subnormal ? (input_fraction << leading_shift) : input_fraction;
    wire signed [8:0] root_e = input_subnormal ?
        (use_bf16 ? -9'sd126 : -9'sd14) - $signed({5'd0, leading_shift}) : input_e;
    wire parity = root_e[0];

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
    wire [12:0] root_t = use_bf16 ? {4'd0, root_fraction[9:3], 2'd0} : {root_fraction, 3'd0};
    wire [12:0] t = select_exp ? exp_z[12:0] : root_t;

    // 3. 区間中心からの残差dと係数c0・c1を選ぶ
    // 区間内の下位bitのMSB反転は「下位bit値-区間幅/2」のsigned表現になる。
    // rsqrtの表はparity=0が前半、parity=1が後半。""".splitlines()
    for name, (fraction_bits, coefficient_q, index_widths) in PROFILES.items():
        value_q, slope_q = coefficient_q
        dropped = 2 if fraction_bits == 10 else 1
        quantized = {}
        lines += ["", f"    // {name.upper()}: dはQ{value_q-dropped}、c0はQ{value_q}、c1はQ{slope_q}。"]
        for op, index_bits in zip(OPS, index_widths):
            prefix = f"{name}_{op}"
            ideal = coefficients(op, index_bits)
            quantized[op] = [np.rint(ideal[:, i] * (1 << q)).astype(np.int64)
                             for i, q in enumerate(coefficient_q)]
            domain = Domain(fraction_bits, op, np.zeros(65536, dtype=np.int64))
            residual_values, _, _ = residual(domain, index_bits, value_q)
            assert width(residual_values >> dropped, True) <= 7
            residual_bits = value_q - index_bits - dropped
            index = f"t[{value_q-1}:{value_q-index_bits}]"
            if op == "rsqrt":
                index = "{parity, " + index + "}"
            lines += [f"    // {op}: {1 << index_bits}区間" +
                      ("×指数偶奇2通り。" if op == "rsqrt" else "。"),
                      f"    wire [{index_bits+(op == 'rsqrt')-1}:0] {prefix}_index = {index};",
                      f"    wire signed [{residual_bits-1}:0] {prefix}_d = "
                      f"{{~t[{value_q-index_bits-1}], t[{value_q-index_bits-2}:{dropped}]}};"]
            for i, values in enumerate(quantized[op]):
                bits = width(values, i == 1)
                assert bits <= (14 if i == 0 else 9)
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
        residuals = [f"$signed({extend(name+'_'+op+'_d',value_q-b-dropped,7,True)})"
                     for op, b in zip(OPS, index_widths)]
        lines += [f"    // {name.upper()}内で演算を選択し、共有カーネルの幅へ明示的に拡張する。",
                  f"    wire signed [6:0] {name}_d =",
                  f"        select_exp   ? {residuals[0]} :",
                  f"        select_recip ? {residuals[1]} :",
                  f"                       {residuals[2]};"]
        for i, w in enumerate((14, 9)):
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
    // 4. 一つの7×9乗算器で、一次近似y=c0+floor(d*c1)を計算する
    // 小数点位置は形式ごとに維持し、符号拡張だけで共有乗算器へ渡す。
    wire signed [6:0] d = use_bf16 ? bf16_d : fp16_d;
    wire [13:0] c0 = use_bf16 ? bf16_c0 : fp16_c0;
    wire signed [8:0] c1 = use_bf16 ? bf16_c1 : fp16_c1;
    wire signed [15:0] product = d * c1;
    // 積はFP16: Q18、BF16: Q13。5／4 bit右へ切り下げ、c0と同じQ13／Q9に戻す。
    // signedの上位sliceは負方向へのfloor。最終出力ではRNEする。
    wire signed [15:0] correction = use_bf16 ? $signed({{4{product[15]}}, product[15:4]})
                                          : $signed({{5{product[15]}}, product[15:5]});
    wire signed [15:0] polynomial = $signed({2'd0, c0}) + correction;
    // recip(m=1)、rsqrt(m=1かつ偶数指数)は近似せず、厳密な1を選択する。
    wire exact_root = !select_exp & (~|root_fraction) & (select_recip | !parity);
    wire [13:0] y = exact_root ? (use_bf16 ? 14'd512 : 14'd8192) : polynomial[13:0];

    // 5. 正規化、指数復元、出力形式へのRNE
    // 根系の非厳密点は[0.5,1)。expの1未満の値も、出力RNEでは必ず1へ丸まる。
    // 全入力の丸め・FTZ照合により、近似結果を待たずに正規化位置を決められる。
    wire signed [2:0] normalization = (select_exp | exact_root) ? 3'sd0 : -3'sd1;
    wire signed [8:0] exp_scale = use_bf16 ? $signed(exp_z[17:9]) : $signed(exp_z[21:13]);
    // exp: floor(z)、recip: -e、rsqrt: -floor(e/2)を復元する。
    wire signed [8:0] scale = select_exp ? exp_scale : select_recip ? -root_e : -(root_e >>> 1);
    wire signed [9:0] biased_before = $signed({scale[8], scale}) + (use_bf16 ? 10'sd127 : 10'sd15)
                                   + $signed({{7{normalization[2]}}, normalization});
    // underflow時は最小normalの仮数位置へそろえる。FTZでも境界のRNEは保持する。
    wire near_underflow = SUPPORT_SUBNORMAL ? (biased_before <= 10'sd0) : (biased_before == 10'sd0);
    wire signed [2:0] pack_adjust = normalization + $signed({2'd0, near_underflow});""".splitlines()
    # 保持部(f+1 bit)とguard・stickyを選ぶ。丸め加算そのものは形式間で共有する。
    for name, (f, (q, _), _) in PROFILES.items():
        expr = grs("y", q+1, q-f+1, f+1)
        for adjustment in (0, -1):
            expr = f"(pack_adjust == {literal(adjustment,3,True)}) ? {grs('y',q+1,q-f+adjustment,f+1)} :\n        " + expr
        lines += [f"    wire [{f+2}:0] {name}_pack_grs = {expr};"]
    lines += """    // 追加の右shiftは丸め前に行い、捨てるbitをstickyへ集約する。
    // 13 bit以上のshiftは同じzeroへ丸まるため、制御幅を4 bitへ制限する。
    wire [3:0] denormal_shift = (SUPPORT_SUBNORMAL && biased_before < 10'sd0) ?
        ((biased_before < -10'sd12) ? 4'd13 : (4'd0 - biased_before[3:0])) : 4'd0;
    wire [12:0] unshifted_grs = use_bf16 ? {3'd0, bf16_pack_grs} : fp16_pack_grs;""".splitlines()
    previous = "unshifted_grs"
    for stage, shift in enumerate((1, 2, 4, 8)):
        signal = "pack_grs" if stage == 3 else f"denormal_grs_{shift}"
        lines += [f"    wire [12:0] {signal} = denormal_shift[{stage}] ?",
                  f"        {{{shift}'d0, {previous}[12:{shift+1}], (|{previous}[{shift}:0])}} : {previous};"]
        previous = signal
    lines += """    // pack_grs[12:2]が保持部、[1]がguard、[0]がsticky。最終RNEは一度だけ。
    // 現行係数・残差幅では、RNE後も仮数が2に達しないことを全入力で確認する。
    // min normalへの繰上げは隠れbitへ反映し、normalの指数carryとは区別する。
    wire [10:0] packed_m = pack_grs[12:2] + {10'd0, (pack_grs[1] & (pack_grs[0] | pack_grs[2]))};
    wire signed [9:0] packed_e = near_underflow ? 10'sd1 : biased_before;
    wire [9:0] packed_fraction = use_bf16 ? {3'd0, packed_m[6:0]} : packed_m[9:0];
    // 正のInf: BF16=0x7f80、FP16=0x7c00。qNaN: BF16=0x7fc0、FP16=0x7e00。
    wire [14:0] inf = use_bf16 ? 15'd32640 : 15'd31744;
    wire [15:0] nan = use_bf16 ? 16'd32704 : 16'd32256;
    wire [14:0] normal_payload = use_bf16 ? {packed_e[7:0], packed_fraction[6:0]} : {packed_e[4:0], packed_fraction};
    wire tiny_result = packed_m < (use_bf16 ? 11'd128 : 11'd1024);
    wire [14:0] finite_payload = SUPPORT_SUBNORMAL && near_underflow && tiny_result ?
                                {5'd0, packed_fraction} :
                                (biased_before < 10'sd0 || tiny_result) ? 15'd0
                              : (packed_e >= (use_bf16 ? 10'sd255 : 10'sd31)) ? inf : normal_payload;

    // 6. 特殊値と無効opの選択（近似結果より優先する）
    // expの|x|>=128は両形式ともoverflow／FTZとなり、近似経路を使わない。
    wire is_nan = exponent_all_ones & !fraction_zero;
    wire negative_rsqrt = select_rsqrt & x[15] & !input_zero;
    wire exp_large = input_e >= 9'sd7;
    // exp(±0)=1: BF16=0x3f80、FP16=0x3c00。
    wire [15:0] exp_result = exponent_zero ? (use_bf16 ? 16'd16256 : 16'd15360)
                           : exp_large ? (x[15] ? 16'd0 : {1'b0, inf}) : {1'b0, finite_payload};
    wire [15:0] root_result = input_zero ? {x[15], inf}
                            : exponent_all_ones ? {(select_recip & x[15]), 15'd0}
                            : {(select_recip & x[15]), finite_payload};
    assign result = (!valid_op | is_nan | negative_rsqrt) ? nan : select_exp ? exp_result : root_result;
endmodule
""".splitlines()
    return "\n".join(lines) + "\n"


def vectors(name, refs, support_subnormal):
    f, qs, bs = PROFILES[name]
    outputs, metrics = [], []
    for oi, (op, b) in enumerate(zip(OPS, bs)):
        domain = Domain(f, op, refs[0 if f == 10 else 1, oi], support_subnormal)
        out = linear(domain, b, *qs)
        metric = domain.metrics(out)
        assert metric["violations"] == metric["monotonic"] == 0, (name, op, metric)
        outputs.append(out)
        metrics.append(metric)
    data = np.array(outputs, dtype="<u2").tobytes()
    directory = Path(f"build/subnormal-{int(support_subnormal)}")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.bin").write_bytes(data)
    (directory / f"{name}.json").write_text(json.dumps({"profile": PROFILES[name], "metrics": metrics,
        "support_subnormal": bool(support_subnormal),
        "vectors_sha256": hashlib.sha256(data).hexdigest()}, indent=2)+"\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--vectors", action="store_true")
    parser.add_argument("--support-subnormal", type=int, choices=(0, 1), default=1)
    args = parser.parse_args()
    Path("rtl").mkdir(exist_ok=True)
    text = generate()
    path = Path("rtl/fp16.sv")
    if args.check:
        assert path.read_text() == text, path
    else:
        path.write_text(text)
    if args.vectors:
        reference = "build/reference-subnormal.bin" if args.support_subnormal else "build/reference.bin"
        refs = np.fromfile(reference, dtype="<u2").reshape(2, 3, 65536)
        for name in PROFILES:
            vectors(name, refs, args.support_subnormal)
    print("RTL generation check: PASS" if args.check else "RTL generation: PASS")


if __name__ == "__main__":
    main()
