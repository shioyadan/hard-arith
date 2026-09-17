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
LOG2_C0_FRACTION_BITS = 25
LOG2_C1_FRACTION_BITS = 16
LOG2_C2_FRACTION_BITS = 7
SINE_C0_FRACTION_BITS = 24
SINE_C1_FRACTION_BITS = 15
SINE_C2_FRACTION_BITS = 5
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
    right_endpoint: bool = False,
    direction: int = 0,
):
    _, coefficient_c1, coefficient_c2 = chebyshev_quadratic(
        function, center-half_width if right_endpoint else center, half_width
    )
    if right_endpoint:
        coefficient_c1 += 2*half_width*coefficient_c2
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
    if right_endpoint:
        samples -= half_integer
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
            # 右端基準ではd<=0。内側の値とその段差を逆符号にして逆行を防ぐ。
            if direction and (direction*c1 < 0 or direction*c2 > 0):
                continue
            inner_bits = C1_FRACTION_BITS+1 if right_endpoint else c1_fraction_bits
            output_bits = (REDUCED_C0_FRACTION_BITS
                           if right_endpoint else c0_fraction_bits)
            inner = (c1 << (inner_bits-c1_fraction_bits))+round_signed_shift_array(
                samples*c2,
                DELTA_FRACTION_BITS+c2_fraction_bits-inner_bits,
            )
            correction = round_signed_shift_array(
                samples*inner,
                DELTA_FRACTION_BITS+inner_bits-output_bits,
            )
            ideal_c0 = (exact*(1 << c0_fraction_bits)
                        - correction*2.0**(c0_fraction_bits-output_bits))
            center_c0 = round((float(ideal_c0.min())+float(ideal_c0.max()))/2)
            if right_endpoint:
                center_c0 = min(center_c0, (1 << c0_fraction_bits)-1)
            for c0 in range(center_c0-2, center_c0+3):
                # 右端基準はsin用。極値近傍もC0<1とし、共通prefixを維持する。
                if right_endpoint and not 0 <= c0 < (1 << c0_fraction_bits):
                    continue
                maximum_error = float(np.max(np.abs(
                    c0*2.0**-c0_fraction_bits+correction*2.0**-output_bits-exact
                )))
                if best is None or maximum_error < best[0]:
                    best = (maximum_error, c0, c1, c2)
    assert best is not None
    return best[1], best[2], best[3], best[0]


def choose_monotonic_path(domains, direction, endpoint):
    """各行の候補から、境界と最後の厳密点まで単調な最小変更列を選ぶ。"""
    if not domains or direction not in (-1, 1):
        raise ValueError("空のtableまたは不正な単調方向です")
    states = [(0, [])]
    for candidates in domains:
        next_states = []
        for candidate in candidates:
            compatible = [state for state in states if not state[1]
                          or direction*(candidate[1]-state[1][-1][2]) >= 0]
            if compatible:
                cost, path = min(compatible, key=lambda state: state[0])
                next_states.append((cost+candidate[3], path+[candidate]))
        if not next_states:
            raise ValueError("table境界を単調にするC0列がありません")
        states = next_states
    states = [state for state in states
              if direction*(endpoint-state[1][-1][2]) >= 0]
    if not states:
        raise ValueError("最終境界を単調にするC0列がありません")
    _, path = min(states, key=lambda state: state[0])
    return path


def make_monotonic_rows(
    name, function, count, interval, base, bits, direction, right_endpoint=False,
):
    """Q18中間値の全残差と最終丸めを検査し、境界も単調になる係数列を選ぶ。"""
    c0_bits, c1_bits, c2_bits = bits
    half_integer = round(interval*(1 << (DELTA_FRACTION_BITS-1)))
    delta = np.arange(-half_integer, half_integer, dtype=np.int64)
    if right_endpoint:
        delta -= half_integer
    domains = []
    rows = []
    for index in range(count):
        center = base+(index+(1 if right_endpoint else 0.5))*interval
        row = tune_row(
            function, center, interval/2, *bits, right_endpoint=right_endpoint,
            direction=direction if right_endpoint else 0,
        )
        c0, c1, c2, _ = row
        rows.append(row)
        inner = (c1 << (C1_FRACTION_BITS+1-c1_bits))+round_signed_shift_array(
            delta*c2, DELTA_FRACTION_BITS+c2_bits-(C1_FRACTION_BITS+1),
        )
        correction = round_signed_shift_array(
            delta*inner,
            DELTA_FRACTION_BITS+(C1_FRACTION_BITS+1)-REDUCED_C0_FRACTION_BITS,
        )
        # binary64は探索用。採用後は独立した整数／高精度参照でRTLを全数検査する。
        exact = np.array([function(center+int(d)*2.0**-DELTA_FRACTION_BITS)
                          for d in delta])
        reference = exact.astype(np.float32).view(np.uint32).astype(np.int64)
        if base == 0:
            arguments = center+delta*2.0**-DELTA_FRACTION_BITS
            lower_reference = np.array([
                function(max(0.0, float(x)-2.0**-24)) for x in arguments])
            upper_reference = np.array([
                function(min(0.5, float(x)+2.0**-24)) for x in arguments])
        candidates = []
        for candidate_c0 in range(c0-4, c0+5):
            c0_limit = 1 << (c0_bits if right_endpoint else c0_bits+1)
            if not 0 <= candidate_c0 < c0_limit:
                continue
            fixed = (candidate_c0 << (REDUCED_C0_FRACTION_BITS-c0_bits))+correction
            output = (fixed*2.0**-REDUCED_C0_FRACTION_BITS).astype(np.float32)
            # 多項式を通らない厳密点も隣接判定に含める。
            if index == 0 and (base == 0 or function(base) == 1):
                output[0] = function(base)
            if np.any(direction*np.diff(output.astype(np.float64)) < 0):
                continue
            error = float(np.max(np.abs(output.astype(np.float64)-exact)))
            if base == 0:
                # Q23位相cellの両端まで検査する。極値付近にpiの最大勾配を課さない。
                error = max(float(np.max(np.abs(output-lower_reference))),
                            float(np.max(np.abs(output-upper_reference))))
                good = error <= 4*2.0**-23
            else:
                good = np.max(np.abs(
                    output.view(np.uint32).astype(np.int64)-reference)) <= 1
            if good:
                candidates.append((candidate_c0, float(output[0]), float(output[-1]),
                                   abs(candidate_c0-c0), error))
        if not candidates:
            raise SystemExit(f"{name}の区間{index}に精度と単調性を満たすC0がありません")
        domains.append(candidates)

    # 最終行から次のbinade／sinの極値への接続も検査する。
    endpoint = float(np.float32(function(base+count*interval)))
    try:
        path = choose_monotonic_path(domains, direction, endpoint)
    except ValueError as error:
        raise SystemExit(f"{name}: {error}") from error
    return [(candidate[0], row[1], row[2], candidate[4])
            for row, candidate in zip(rows, path)]


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
    if name == "sine":
        delta -= half_integer
    if name == "exp2":
        limits = {
            "inner_product": (-(1 << 31), (1 << 31)-1),
            "inner_correction": (-(1 << 13), (1 << 13)-1),
            "inner": (-(1 << 20), (1 << 20)-1),
            "outer_product": (-(1 << 39), (1 << 39)-1),
            "outer_correction": (-(1 << 21), (1 << 21)-1),
            "polynomial": (-(1 << 28), (1 << 28)-1),
        }
    else:
        limits = {
            "inner_product": (-(1 << 31), (1 << 31)-1),
            "inner_correction": (-(1 << 14), (1 << 14)-1),
            "inner": (-(1 << 20), (1 << 20)-1),
            "outer_product": (-(1 << 39), (1 << 39)-1),
            "outer_correction": (-(1 << 20), (1 << 20)-1),
            "polynomial": (-(1 << 26), (1 << 26)-1),
        }
    observed = {key: [None, None] for key in limits}
    # 非exp2の入力格子もRTLのQ24へ揃え、実際の積の宣言幅と比較する。
    datapath_delta = delta << (EXP2_DELTA_FRACTION_BITS-delta_fraction_bits)

    for c0, c1, c2, _ in rows:
        c2_q9 = c2 << (C2_FRACTION_BITS-c2_fraction_bits)
        inner_product = datapath_delta*c2_q9
        if name == "exp2":
            c1_value = c1 << 1
            inner_correction = round_signed_shift_array(
                inner_product,
                EXP2_DELTA_FRACTION_BITS+C2_FRACTION_BITS-c1_fraction_bits,
            )
            inner = c1_value+inner_correction
            outer_product = datapath_delta*inner
            outer_correction = round_signed_shift_array(
                outer_product,
                EXP2_DELTA_FRACTION_BITS+c1_fraction_bits-c0_fraction_bits,
            )
            polynomial = c0+outer_correction
        else:
            c1_value = c1 << (C1_FRACTION_BITS+1-c1_fraction_bits)
            inner_correction = round_signed_shift_array(
                inner_product,
                EXP2_DELTA_FRACTION_BITS+C2_FRACTION_BITS-(C1_FRACTION_BITS+1),
            )
            inner = c1_value+inner_correction
            outer_product = datapath_delta*inner
            outer_correction = round_signed_shift_array(
                outer_product,
                EXP2_DELTA_FRACTION_BITS+(C1_FRACTION_BITS+1)
                - REDUCED_C0_FRACTION_BITS,
            )
            polynomial = (
                c0 << (REDUCED_C0_FRACTION_BITS-c0_fraction_bits)
            )+outer_correction
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
    root_bits = (REDUCED_C0_FRACTION_BITS, C1_FRACTION_BITS, REDUCED_C2_FRACTION_BITS)
    sqrt_base = make_monotonic_rows(
        "sqrt_base", math.sqrt, 64, 1.0/64, 1.0, root_bits, 1)
    sqrt_scaled = make_monotonic_rows(
        "sqrt_scaled", lambda value: math.sqrt(2.0*value),
        64, 1.0/64, 1.0, root_bits, 1)
    rsqrt_base = make_monotonic_rows(
        "rsqrt_base", lambda value: 1.0/math.sqrt(value),
        128, 1.0/128, 1.0, root_bits, -1)
    rsqrt_scaled = make_monotonic_rows(
        "rsqrt_scaled", lambda value: 1.0/math.sqrt(2.0*value),
        128, 1.0/128, 1.0, root_bits, -1
    )
    log2 = make_rows(
        math.log2, 64, 1.0/64,
        c0_fraction_bits=LOG2_C0_FRACTION_BITS,
        c1_fraction_bits=LOG2_C1_FRACTION_BITS,
        c2_fraction_bits=LOG2_C2_FRACTION_BITS,
    )
    exp2 = make_exp2_rows()
    sine = make_monotonic_rows(
        "sine", lambda value: math.sin(math.pi*value),
        64, 1.0/128, 0.0,
        (SINE_C0_FRACTION_BITS, SINE_C1_FRACTION_BITS, SINE_C2_FRACTION_BITS), 1, True,
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
         LOG2_C0_FRACTION_BITS, LOG2_C2_FRACTION_BITS,
         DELTA_FRACTION_BITS, LOG2_C1_FRACTION_BITS, False),
        ("exp2", exp2, 1 << 17,
         EXP2_C0_FRACTION_BITS, C2_FRACTION_BITS,
         EXP2_DELTA_FRACTION_BITS, C1_FRACTION_BITS+1, True),
        ("sine", sine, 1 << 15,
         SINE_C0_FRACTION_BITS, SINE_C2_FRACTION_BITS,
         DELTA_FRACTION_BITS, SINE_C1_FRACTION_BITS, False),
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
        ("log2", log2, LOG2_C0_FRACTION_BITS,
         LOG2_C1_FRACTION_BITS, LOG2_C2_FRACTION_BITS),
        ("exp2", exp2, EXP2_C0_FRACTION_BITS,
         C1_FRACTION_BITS, C2_FRACTION_BITS),
        ("sine", sine, SINE_C0_FRACTION_BITS,
         SINE_C1_FRACTION_BITS, SINE_C2_FRACTION_BITS),
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
