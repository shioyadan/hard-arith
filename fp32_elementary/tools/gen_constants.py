#!/usr/bin/env python3
"""FP32Elementaryの量子化済み区分二次係数を生成・照合する。"""

from __future__ import annotations

import argparse
import math
import re
from pathlib import Path

import numpy as np


REDUCED_C0_FRACTION_BITS = 25
C1_FRACTION_BITS = 17
C2_FRACTION_BITS = 9
REDUCED_C2_FRACTION_BITS = 8
DELTA_FRACTION_BITS = 23
EXP2_C0_FRACTION_BITS = 27
EXP2_DELTA_FRACTION_BITS = 24
LINEAR_SEARCH_RADIUS = 12
QUADRATIC_SEARCH_RADIUS = 8
GRID_DIVISIONS = 4096
BEGIN_MARKER = "// BEGIN GENERATED ELEMENTARY TABLES"
END_MARKER = "// END GENERATED ELEMENTARY TABLES"


def round_signed_shift_array(values, shift: int):
    return (values+(1 << (shift-1))) >> shift


def chebyshev_quadratic(function, center: float, half_width: float):
    nodes = np.array([
        half_width*math.cos((2*index-1)*math.pi/6)
        for index in range(1, 4)
    ])
    values = np.array([function(center+float(node)) for node in nodes])
    matrix = np.column_stack((np.ones_like(nodes), nodes, nodes*nodes))
    return np.linalg.solve(matrix, values)


def tune_row(
    function,
    center: float,
    half_width: float,
    c0_fraction_bits: int,
    c1_fraction_bits: int,
    c2_fraction_bits: int,
):
    _, coefficient_c1, coefficient_c2 = chebyshev_quadratic(
        function, center, half_width
    )
    center_c1 = round(coefficient_c1*(1 << c1_fraction_bits))
    center_c2 = round(coefficient_c2*(1 << c2_fraction_bits))
    half_integer = round(half_width*(1 << DELTA_FRACTION_BITS))
    samples = np.array(sorted({
        -half_integer,
        half_integer-1,
        *(
            -half_integer
            + ((2*half_integer-1)*sample)//GRID_DIVISIONS
            for sample in range(GRID_DIVISIONS+1)
        ),
    }), dtype=np.int64)
    exact = np.array([
        function(center+int(delta)*2.0**-DELTA_FRACTION_BITS)
        for delta in samples
    ])
    best = None
    for c1 in range(
        center_c1-LINEAR_SEARCH_RADIUS,
        center_c1+LINEAR_SEARCH_RADIUS+1,
    ):
        for c2 in range(
            center_c2-QUADRATIC_SEARCH_RADIUS,
            center_c2+QUADRATIC_SEARCH_RADIUS+1,
        ):
            inner = c1+round_signed_shift_array(
                samples*c2,
                DELTA_FRACTION_BITS+c2_fraction_bits-c1_fraction_bits,
            )
            correction = round_signed_shift_array(
                samples*inner,
                DELTA_FRACTION_BITS+c1_fraction_bits-c0_fraction_bits,
            )
            ideal_c0 = exact*(1 << c0_fraction_bits)-correction
            center_c0 = round((float(ideal_c0.min())+float(ideal_c0.max()))/2)
            for c0 in range(center_c0-2, center_c0+3):
                maximum_error = float(np.max(np.abs(
                    (c0+correction)*2.0**-c0_fraction_bits-exact
                )))
                if best is None or maximum_error < best[0]:
                    best = (maximum_error, c0, c1, c2)
    assert best is not None
    return best[1], best[2], best[3], best[0]


def binary32_q(bits, fraction_bits: int):
    """正のnormal binary32 bit列を指定Q形式の厳密な整数へ直す。"""
    bits = np.asarray(bits, dtype=np.uint32)
    exponent = ((bits >> 23) & 0xff).astype(np.int64)-127
    significand = ((bits & 0x7fffff) | 0x800000).astype(np.int64)
    return significand << (exponent+fraction_bits-23)


def exp2_polynomial_bounds(index: int):
    """量子化残差の各cell全体で1 ULPを満たすQ27上下限を返す。"""
    half_integer = 1 << (EXP2_DELTA_FRACTION_BITS-7)
    delta = np.arange(-half_integer, half_integer+1, dtype=np.int64)
    unit = 2.0**-EXP2_DELTA_FRACTION_BITS
    lower_argument = index/64.0+(delta-0.5)*unit
    upper_argument = index/64.0+(delta+0.5)*unit
    lower_reference = np.exp2(lower_argument).astype(np.float32).view(np.uint32)
    upper_reference = np.exp2(upper_argument).astype(np.float32).view(np.uint32)

    # exp2は単調増加なので、cell両端のRNE値から許容出力codeの共通範囲を得る。
    lowest_output = upper_reference-1
    highest_output = lower_reference+1

    # Q27 packerが許容codeへ丸める整数範囲を、隣接値との中点から逆算する。
    lower_sum = (
        binary32_q(lowest_output-1, EXP2_C0_FRACTION_BITS)
        + binary32_q(lowest_output, EXP2_C0_FRACTION_BITS)
    )
    upper_sum = (
        binary32_q(highest_output, EXP2_C0_FRACTION_BITS)
        + binary32_q(highest_output+1, EXP2_C0_FRACTION_BITS)
    )
    lower = (lower_sum+1)//2
    lower += ((lower_sum & 1) == 0) & ((lowest_output & 1) != 0)
    upper = upper_sum//2
    upper -= ((upper_sum & 1) == 0) & ((highest_output & 1) != 0)
    return delta, lower.astype(np.int64), upper.astype(np.int64)


def pack_exp2_reduced_q27(value):
    """[2^-1,2)の正のQ27値をbinary32 RNE codeへ変換する。"""
    value = np.asarray(value, dtype=np.int64)
    shift = np.where(value < (1 << 27), 3, 4)
    quotient = value >> shift
    remainder = value & ((1 << shift)-1)
    half = 1 << (shift-1)
    quotient += (remainder > half) | (
        (remainder == half) & ((quotient & 1) != 0)
    )
    exponent = np.where(value < (1 << 27), 126, 127)
    return (exponent << 23)+(quotient-(1 << 23))


def make_exp2_rows():
    """最終1 ULP条件と単調性へC0を合わせたexp2係数を作る。"""
    rows = make_centered_rows(
        lambda value: 2.0**value,
        [index/64.0 for index in range(64)],
        1.0/128,
        26,
        C1_FRACTION_BITS,
        C2_FRACTION_BITS,
    )
    domains = []
    for index, (c0, c1, c2, error) in enumerate(rows):
        delta, lower, upper = exp2_polynomial_bounds(index)
        c1_q18 = c1 << 1
        inner = c1_q18+round_signed_shift_array(
            delta*c2,
            EXP2_DELTA_FRACTION_BITS+C2_FRACTION_BITS-(C1_FRACTION_BITS+1),
        )
        correction = round_signed_shift_array(
            delta*inner,
            EXP2_DELTA_FRACTION_BITS+(C1_FRACTION_BITS+1)
            - EXP2_C0_FRACTION_BITS,
        )
        lowest_c0 = int(np.max(lower-correction))
        highest_c0 = int(np.min(upper-correction))
        if lowest_c0 > highest_c0:
            raise SystemExit(f"exp2 table {index}に1 ULPを満たすC0がありません")
        scaled_c0 = c0 << (EXP2_C0_FRACTION_BITS-26)
        candidates = []
        for candidate_c0 in range(lowest_c0, highest_c0+1):
            output = pack_exp2_reduced_q27(candidate_c0+correction)
            if np.any(np.diff(output) < 0):
                continue
            candidates.append((
                candidate_c0,
                int(output[0]),
                int(output[-1]),
                abs(candidate_c0-scaled_c0),
            ))
        if not candidates:
            raise SystemExit(f"exp2 table {index}に単調なC0がありません")
        domains.append(candidates)

    # 隣接table境界と63->0の指数繰り上がりも含め、変更量最小のC0列を選ぶ。
    best = None
    for first in domains[0]:
        states = [(first[3], [first])]
        for candidates in domains[1:]:
            next_states = []
            for candidate in candidates:
                compatible = [
                    state for state in states
                    if state[1][-1][2] <= candidate[1]
                ]
                if compatible:
                    cost, path = min(compatible, key=lambda state: state[0])
                    next_states.append((cost+candidate[3], path+[candidate]))
            states = next_states
        for cost, path in states:
            if path[-1][2] <= first[1]+(1 << 23):
                candidate = (cost, path)
                if best is None or candidate[0] < best[0]:
                    best = candidate
    if best is None:
        raise SystemExit("exp2 table境界を単調にするC0列がありません")

    return [
        (candidate[0], c1, c2, error)
        for candidate, (_, c1, c2, error) in zip(best[1], rows)
    ]


def make_rows(
    function,
    count: int,
    interval: float,
    base: float = 1.0,
    c0_fraction_bits: int = REDUCED_C0_FRACTION_BITS,
    c1_fraction_bits: int = C1_FRACTION_BITS,
    c2_fraction_bits: int = REDUCED_C2_FRACTION_BITS,
):
    return [
        tune_row(
            function,
            base+(index+0.5)*interval,
            interval/2,
            c0_fraction_bits,
            c1_fraction_bits,
            c2_fraction_bits,
        )
        for index in range(count)
    ]


def make_centered_rows(
    function,
    centers,
    half_width: float,
    c0_fraction_bits: int = REDUCED_C0_FRACTION_BITS,
    c1_fraction_bits: int = C1_FRACTION_BITS,
    c2_fraction_bits: int = REDUCED_C2_FRACTION_BITS,
):
    return [
        tune_row(
            function,
            center,
            half_width,
            c0_fraction_bits,
            c1_fraction_bits,
            c2_fraction_bits,
        )
        for center in centers
    ]


def validate_datapath_ranges(
    name: str,
    rows,
    half_integer: int,
    c0_fraction_bits: int,
    c2_fraction_bits: int,
    delta_fraction_bits: int = DELTA_FRACTION_BITS,
    c1_fraction_bits: int = C1_FRACTION_BITS,
    include_upper_endpoint: bool = False,
):
    """生成係数を共有Horner datapathへ通し、切り詰めた幅を全残差で検査する。"""
    delta = np.arange(
        -half_integer,
        half_integer+int(include_upper_endpoint),
        dtype=np.int64,
    )
    limits = {
        "inner_product": (-(1 << 31), (1 << 31)-1),
        "inner_correction": (
            -(1 << (c1_fraction_bits-5)),
            (1 << (c1_fraction_bits-5))-1,
        ),
        "inner": (
            -(1 << (c1_fraction_bits+2)),
            (1 << (c1_fraction_bits+2))-1,
        ),
        "outer_product": (-(1 << 39), (1 << 39)-1),
        "outer_correction": (
            -(1 << (c0_fraction_bits-6)),
            (1 << (c0_fraction_bits-6))-1,
        ),
        "polynomial": (
            -(1 << (c0_fraction_bits+1)),
            (1 << (c0_fraction_bits+1))-1,
        ),
    }
    observed = {key: [None, None] for key in limits}

    for c0, c1, c2, _ in rows:
        c2_q9 = c2 << (C2_FRACTION_BITS-c2_fraction_bits)
        c1_value = c1 << (c1_fraction_bits-C1_FRACTION_BITS)
        inner_product = delta*c2_q9
        inner_correction = round_signed_shift_array(
            inner_product,
            delta_fraction_bits+C2_FRACTION_BITS-c1_fraction_bits,
        )
        inner = c1_value+inner_correction
        outer_product = delta*inner
        outer_correction = round_signed_shift_array(
            outer_product,
            delta_fraction_bits+c1_fraction_bits-c0_fraction_bits,
        )
        polynomial = c0+outer_correction
        values = {
            "inner_product": inner_product,
            "inner_correction": inner_correction,
            "inner": inner,
            "outer_product": outer_product,
            "outer_correction": outer_correction,
            "polynomial": polynomial,
        }
        for key, value in values.items():
            minimum = int(value.min())
            maximum = int(value.max())
            observed[key][0] = minimum if observed[key][0] is None else min(
                observed[key][0], minimum
            )
            observed[key][1] = maximum if observed[key][1] is None else max(
                observed[key][1], maximum
            )

    for key, (minimum, maximum) in observed.items():
        lower, upper = limits[key]
        if minimum < lower or maximum > upper:
            raise SystemExit(
                f"{name}の{key}が宣言幅を超えます: "
                f"[{minimum}, {maximum}] not in [{lower}, {upper}]"
            )


def compressed_array(name: str, width: int, values, column: int):
    bit_values = [row[column] & ((1 << width)-1) for row in values]
    difference = 0
    for value in bit_values[1:]:
        difference |= value ^ bit_values[0]
    prefix_width = width-difference.bit_length()
    if prefix_width == 0:
        raise SystemExit(f"{name}に暗黙化できる上位bitがありません")
    suffix_width = width-prefix_width
    prefix = bit_values[0] >> suffix_width
    lines = [
        f"    localparam [{prefix_width-1}:0] {name}_prefix = "
        f"{prefix_width}'b{prefix:0{prefix_width}b};",
        f"    localparam [{suffix_width-1}:0] {name}_suffix [0:{len(values)-1}] = '{{",
    ]
    suffix_mask = (1 << suffix_width)-1
    for start in range(0, len(bit_values), 4):
        chunk = bit_values[start:start+4]
        entries = ", ".join(
            f"{suffix_width}'d{value & suffix_mask}" for value in chunk
        )
        comma = "," if start+len(chunk) < len(bit_values) else ""
        lines.append(
            f"        {entries}{comma} // {start} .. {start+len(chunk)-1}"
        )
    lines.append("    };")
    return lines


def append_tables(
    lines,
    prefix: str,
    rows,
    c0_fraction_bits: int,
    c1_fraction_bits: int,
    c2_fraction_bits: int,
):
    lines.extend(compressed_array(
        f"{prefix}_c0_q{c0_fraction_bits}",
        c0_fraction_bits+2,
        rows,
        0,
    ))
    lines.append("")
    lines.extend(compressed_array(
        f"{prefix}_c1_q{c1_fraction_bits}",
        c1_fraction_bits+3,
        rows,
        1,
    ))
    lines.append("")
    lines.extend(compressed_array(
        f"{prefix}_c2_q{c2_fraction_bits}",
        c2_fraction_bits+4,
        rows,
        2,
    ))


def generate_block() -> str:
    reciprocal = make_rows(lambda value: 1.0/value, 128, 1.0/128)
    sqrt_base = make_rows(math.sqrt, 64, 1.0/64)
    sqrt_scaled = make_rows(lambda value: math.sqrt(2.0*value), 64, 1.0/64)
    rsqrt_base = make_rows(lambda value: 1.0/math.sqrt(value), 128, 1.0/128)
    rsqrt_scaled = make_rows(
        lambda value: 1.0/math.sqrt(2.0*value), 128, 1.0/128
    )
    log2 = make_rows(math.log2, 64, 1.0/64)
    exp2 = make_exp2_rows()
    sine = make_centered_rows(
        lambda value: math.sin(math.pi*value),
        [(index+0.5)/128.0 for index in range(64)],
        1.0/256,
    )

    for (name, rows, half_integer, c0_fraction_bits, c2_fraction_bits,
         delta_fraction_bits, c1_fraction_bits, include_upper_endpoint) in (
        ("reciprocal", reciprocal, 1 << 15,
         REDUCED_C0_FRACTION_BITS, REDUCED_C2_FRACTION_BITS,
         DELTA_FRACTION_BITS, C1_FRACTION_BITS, False),
        ("sqrt_base", sqrt_base, 1 << 16,
         REDUCED_C0_FRACTION_BITS, REDUCED_C2_FRACTION_BITS,
         DELTA_FRACTION_BITS, C1_FRACTION_BITS, False),
        ("sqrt_scaled", sqrt_scaled, 1 << 16,
         REDUCED_C0_FRACTION_BITS, REDUCED_C2_FRACTION_BITS,
         DELTA_FRACTION_BITS, C1_FRACTION_BITS, False),
        ("rsqrt_base", rsqrt_base, 1 << 15,
         REDUCED_C0_FRACTION_BITS, REDUCED_C2_FRACTION_BITS,
         DELTA_FRACTION_BITS, C1_FRACTION_BITS, False),
        ("rsqrt_scaled", rsqrt_scaled, 1 << 15,
         REDUCED_C0_FRACTION_BITS, REDUCED_C2_FRACTION_BITS,
         DELTA_FRACTION_BITS, C1_FRACTION_BITS, False),
        ("log2", log2, 1 << 16,
         REDUCED_C0_FRACTION_BITS, REDUCED_C2_FRACTION_BITS,
         DELTA_FRACTION_BITS, C1_FRACTION_BITS, False),
        ("exp2", exp2, 1 << 17,
         EXP2_C0_FRACTION_BITS, C2_FRACTION_BITS,
         EXP2_DELTA_FRACTION_BITS, C1_FRACTION_BITS+1, True),
        ("sine", sine, 1 << 15,
         REDUCED_C0_FRACTION_BITS, REDUCED_C2_FRACTION_BITS,
         DELTA_FRACTION_BITS, C1_FRACTION_BITS, False),
    ):
        validate_datapath_ranges(
            name, rows, half_integer, c0_fraction_bits, c2_fraction_bits,
            delta_fraction_bits, c1_fraction_bits, include_upper_endpoint,
        )

    lines = [BEGIN_MARKER]
    for prefix, rows, c0_fraction_bits, c1_fraction_bits, c2_fraction_bits in (
        ("reciprocal", reciprocal, REDUCED_C0_FRACTION_BITS,
         C1_FRACTION_BITS, REDUCED_C2_FRACTION_BITS),
        ("sqrt_base", sqrt_base, REDUCED_C0_FRACTION_BITS,
         C1_FRACTION_BITS, REDUCED_C2_FRACTION_BITS),
        ("sqrt_scaled", sqrt_scaled, REDUCED_C0_FRACTION_BITS,
         C1_FRACTION_BITS, REDUCED_C2_FRACTION_BITS),
        ("rsqrt_base", rsqrt_base, REDUCED_C0_FRACTION_BITS,
         C1_FRACTION_BITS, REDUCED_C2_FRACTION_BITS),
        ("rsqrt_scaled", rsqrt_scaled, REDUCED_C0_FRACTION_BITS,
         C1_FRACTION_BITS, REDUCED_C2_FRACTION_BITS),
        ("log2", log2, REDUCED_C0_FRACTION_BITS,
         C1_FRACTION_BITS, REDUCED_C2_FRACTION_BITS),
        ("exp2", exp2, EXP2_C0_FRACTION_BITS,
         C1_FRACTION_BITS, C2_FRACTION_BITS),
        ("sine", sine, REDUCED_C0_FRACTION_BITS,
         C1_FRACTION_BITS, REDUCED_C2_FRACTION_BITS),
    ):
        append_tables(
            lines,
            prefix,
            rows,
            c0_fraction_bits,
            c1_fraction_bits,
            c2_fraction_bits,
        )
        lines.append("")
    lines.append(END_MARKER)
    return "\n".join(lines)


def replace_block(text: str, block: str) -> str:
    pattern = re.compile(
        rf"^{re.escape(BEGIN_MARKER)}$.*?^{re.escape(END_MARKER)}$",
        re.MULTILINE | re.DOTALL,
    )
    if pattern.search(text) is None:
        raise SystemExit("RTLに生成table markerがありません")
    return pattern.sub(block, text)


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--update", type=Path)
    group.add_argument("--check", type=Path)
    args = parser.parse_args()
    path = args.update or args.check
    assert path is not None
    original = path.read_text()
    expected = replace_block(original, generate_block())
    if args.check is not None:
        if original != expected:
            raise SystemExit(f"再生成したmultifunc定数がRTLと一致しません: {path}")
        print(f"PASS: {path} のelementary定数とtableが一致しました")
    else:
        path.write_text(expected)


if __name__ == "__main__":
    main()
