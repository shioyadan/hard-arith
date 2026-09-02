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
):
    """生成係数を共有Horner datapathへ通し、切り詰めた幅を全残差で検査する。"""
    delta = np.arange(-half_integer, half_integer, dtype=np.int64)
    limits = {
        "inner_product_q32": (-(1 << 30), (1 << 30)-1),
        "inner_correction_q17": (-(1 << 12), (1 << 12)-1),
        "inner_q17": (-(1 << 19), (1 << 19)-1),
        "outer_product_q40": (-(1 << 37), (1 << 37)-1),
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
        inner_product = delta*c2_q9
        inner_correction = round_signed_shift_array(
            inner_product,
            DELTA_FRACTION_BITS+C2_FRACTION_BITS-C1_FRACTION_BITS,
        )
        inner = c1+inner_correction
        outer_product = delta*inner
        outer_correction = round_signed_shift_array(
            outer_product,
            DELTA_FRACTION_BITS+C1_FRACTION_BITS-c0_fraction_bits,
        )
        polynomial = c0+outer_correction
        values = {
            "inner_product_q32": inner_product,
            "inner_correction_q17": inner_correction,
            "inner_q17": inner,
            "outer_product_q40": outer_product,
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
    exp2 = make_centered_rows(
        lambda value: 2.0**value,
        [index/64.0 for index in range(64)],
        1.0/128,
        26,
        C1_FRACTION_BITS,
        C2_FRACTION_BITS,
    )
    sine = make_centered_rows(
        lambda value: math.sin(math.pi*value),
        [(index+0.5)/128.0 for index in range(64)],
        1.0/256,
    )

    for name, rows, half_integer, c0_fraction_bits, c2_fraction_bits in (
        ("reciprocal", reciprocal, 1 << 15,
         REDUCED_C0_FRACTION_BITS, REDUCED_C2_FRACTION_BITS),
        ("sqrt_base", sqrt_base, 1 << 16,
         REDUCED_C0_FRACTION_BITS, REDUCED_C2_FRACTION_BITS),
        ("sqrt_scaled", sqrt_scaled, 1 << 16,
         REDUCED_C0_FRACTION_BITS, REDUCED_C2_FRACTION_BITS),
        ("rsqrt_base", rsqrt_base, 1 << 15,
         REDUCED_C0_FRACTION_BITS, REDUCED_C2_FRACTION_BITS),
        ("rsqrt_scaled", rsqrt_scaled, 1 << 15,
         REDUCED_C0_FRACTION_BITS, REDUCED_C2_FRACTION_BITS),
        ("log2", log2, 1 << 16,
         REDUCED_C0_FRACTION_BITS, REDUCED_C2_FRACTION_BITS),
        ("exp2", exp2, 1 << 16, 26, C2_FRACTION_BITS),
        ("sine", sine, 1 << 15,
         REDUCED_C0_FRACTION_BITS, REDUCED_C2_FRACTION_BITS),
    ):
        validate_datapath_ranges(
            name, rows, half_integer, c0_fraction_bits, c2_fraction_bits
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
        ("exp2", exp2, 26,
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
