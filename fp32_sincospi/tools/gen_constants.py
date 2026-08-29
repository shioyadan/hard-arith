#!/usr/bin/env python3
"""FP32SinCosPiとLite版の近似係数tableを生成・照合する。"""

from __future__ import annotations

import argparse
import math
import re
import struct
from pathlib import Path

import mpmath as mp


A_FRACTION_BITS = 32
B_FRACTION_BITS = 25
C_FRACTION_BITS = 16
D_FRACTION_BITS = 7
SMALL_FRACTION_BITS = 24
TABLE_SIZE = 65
SMALL_MAX_EXPONENT = -9
SMALL_MIN_EXPONENT = -14
SMALL_INTERVALS = 16
BEGIN_MARKER = "// BEGIN GENERATED SINCOSPI TABLES"
END_MARKER = "// END GENERATED SINCOSPI TABLES"
LITE_A_FRACTION_BITS = 24
LITE_B_FRACTION_BITS = 15
LITE_C_FRACTION_BITS = 5
LITE_PHASE_FRACTION_BITS = 23
LITE_TABLE_SIZE = 64
LITE_BEGIN_MARKER = "// BEGIN GENERATED SINCOSPI LITE TABLES"
LITE_END_MARKER = "// END GENERATED SINCOSPI LITE TABLES"


def round_nearest(value: mp.mpf) -> int:
    """正負対称のround-half-away-from-zeroで整数化する。"""
    if value >= 0:
        return int(mp.floor(value + mp.mpf("0.5")))
    return -int(mp.floor(-value + mp.mpf("0.5")))


def quantize(value: mp.mpf, fraction_bits: int) -> int:
    return round_nearest(value * (1 << fraction_bits))


def literal(width: int, value: int, signed: bool) -> str:
    if value < 0:
        return f"-{width}'sd{-value}"
    kind = "sd" if signed else "d"
    return f"{width}'{kind}{value}"


def table_array(
    name: str,
    width: int,
    values: list[tuple[str, int]],
    signed: bool,
    items_per_line: int = 4,
) -> list[str]:
    lines = [f"    localparam [{width - 1}:0] {name} [0:{len(values) - 1}] = '{{"]
    for position in range(0, len(values), items_per_line):
        chunk = values[position:position+items_per_line]
        entries = ", ".join(literal(width, value, signed) for _, value in chunk)
        comma = "," if position+len(chunk) < len(values) else ""
        first_comment = chunk[0][0]
        last_comment = chunk[-1][0]
        comment = first_comment if len(chunk) == 1 else f"{first_comment} .. {last_comment}"
        lines.append(f"        {entries}{comma} // {comment}")
    lines.append("    };")
    return lines


def small_correction(x: mp.mpf) -> mp.mpf:
    if x == 0:
        return mp.mpf(0)
    return mp.pi - mp.sin(mp.pi * x) / x


def generate_block() -> str:
    mp.mp.dps = 120
    rows: list[tuple[int, int, int, int, int]] = []
    for index in range(TABLE_SIZE):
        center = mp.mpf(index) / 128
        rows.append(
            (
                index,
                quantize(mp.sin(mp.pi * center), A_FRACTION_BITS),
                quantize(mp.pi * mp.cos(mp.pi * center), B_FRACTION_BITS),
                quantize(
                    -mp.pi**2 * mp.sin(mp.pi * center) / 2,
                    C_FRACTION_BITS,
                ),
                quantize(
                    -mp.pi**3 * mp.cos(mp.pi * center) / 6,
                    D_FRACTION_BITS,
                ),
            )
        )

    small_rows: list[tuple[str, int, int]] = []
    for exponent in range(SMALL_MAX_EXPONENT, SMALL_MIN_EXPONENT - 1, -1):
        for interval in range(SMALL_INTERVALS):
            left = (mp.mpf(1) + mp.mpf(interval) / SMALL_INTERVALS) * 2**exponent
            right = (
                mp.mpf(1) + mp.mpf(interval + 1) / SMALL_INTERVALS
            ) * 2**exponent
            base = quantize(small_correction(left), SMALL_FRACTION_BITS)
            next_value = quantize(small_correction(right), SMALL_FRACTION_BITS)
            small_rows.append(
                (f"E = {exponent}, j = {interval}", base, next_value-base)
            )

    lines = [
        BEGIN_MARKER,
        f"    localparam [25:0] pi_q24 = 26'd{quantize(mp.pi, SMALL_FRACTION_BITS)};",
        "",
    ]
    lines.extend(table_array(
        "sine_table_q32", 33,
        [(f"j = {index}", a) for index, a, _, _, _ in rows], False,
    ))
    lines.append("")
    lines.extend(table_array(
        "coefficient_b_table_q25", 27,
        [(f"j = {index}", b) for index, _, b, _, _ in rows], False,
    ))
    lines.append("")
    lines.extend(table_array(
        "coefficient_c_table_q16", 20,
        [(f"j = {index}", c) for index, _, _, c, _ in rows], True,
    ))
    lines.append("")
    lines.extend(table_array(
        "coefficient_d_table_q7", 11,
        [(f"j = {index}", d) for index, _, _, _, d in rows], True,
    ))
    lines.append("")
    lines.extend(table_array(
        "small_correction_base_q24", 11,
        [(comment, base) for comment, base, _ in small_rows], False,
    ))
    lines.append("")
    lines.extend(table_array(
        "small_correction_delta_q24", 7,
        [(comment, delta) for comment, _, delta in small_rows], False,
    ))
    lines.append(END_MARKER)
    return "\n".join(lines)


def round_signed_shift(value: int, shift: int) -> int:
    magnitude = abs(value)
    rounded = (magnitude+(1 << (shift-1))) >> shift
    return -rounded if value < 0 else rounded


def float32(value: float) -> float:
    return struct.unpack("f", struct.pack("f", value))[0]


def tune_lite_coefficients() -> list[tuple[int, int, int, int]]:
    """量子化後のHorner演算を含め、各区間の最大絶対誤差を抑える。"""
    phase_fraction = LITE_PHASE_FRACTION_BITS
    interval_shift = phase_fraction-7
    half_width = 2.0**-8
    adjusted_slope = math.pi-math.pi**3*half_width**2/8.0
    shift_c_to_b = phase_fraction+LITE_C_FRACTION_BITS-LITE_B_FRACTION_BITS
    shift_b_to_a = phase_fraction+LITE_B_FRACTION_BITS-LITE_A_FRACTION_BITS
    rows: list[tuple[int, int, int, int]] = []

    for index in range(LITE_TABLE_SIZE):
        center = (index+0.5)/128.0
        initial_a = round(math.sin(math.pi*center)*(1 << LITE_A_FRACTION_BITS))
        initial_b = round(
            adjusted_slope*math.cos(math.pi*center)*(1 << LITE_B_FRACTION_BITS)
        )
        initial_c = round(
            -math.pi**2*math.sin(math.pi*center)/2
            * (1 << LITE_C_FRACTION_BITS)
        )

        begin = index << interval_shift
        span = (1 << interval_shift)-1
        phases = sorted({begin+(span*sample)//128 for sample in range(129)})
        if index == 0:
            phases = [phase for phase in phases if phase != 0]
        best_error = math.inf
        best = (initial_a, initial_b, initial_c)
        for offset_a in range(-2, 3):
            coefficient_a = initial_a+offset_a
            for offset_b in range(-2, 3):
                coefficient_b = initial_b+offset_b
                for offset_c in range(-2, 3):
                    coefficient_c = initial_c+offset_c
                    maximum = 0.0
                    for phase in phases:
                        delta = phase-begin-(1 << (interval_shift-1))
                        c_term = round_signed_shift(
                            delta*coefficient_c, shift_c_to_b
                        )
                        correction = round_signed_shift(
                            delta*(coefficient_b+c_term), shift_b_to_a
                        )
                        output = float32(
                            (coefficient_a+correction)
                            * 2.0**-LITE_A_FRACTION_BITS
                        )
                        low = (phase-0.5)*2.0**-phase_fraction
                        high = (phase+0.5)*2.0**-phase_fraction
                        maximum = max(
                            maximum,
                            abs(output-math.sin(math.pi*low)),
                            abs(output-math.sin(math.pi*high)),
                        )
                    if maximum < best_error:
                        best_error = maximum
                        best = (coefficient_a, coefficient_b, coefficient_c)
        rows.append((index, *best))
    return rows


def generate_lite_block() -> str:
    rows = tune_lite_coefficients()

    lines = [LITE_BEGIN_MARKER]
    lines.extend(table_array(
        "coefficient_a_table_q24", 25,
        [(f"j = {index}", a) for index, a, _, _ in rows], False,
    ))
    lines.append("")
    lines.extend(table_array(
        "coefficient_b_table_q15", 17,
        [(f"j = {index}", b) for index, _, b, _ in rows], False,
    ))
    lines.append("")
    lines.extend(table_array(
        "coefficient_c_table_q5", 9,
        [(f"j = {index}", c) for index, _, _, c in rows], True,
    ))
    lines.append(LITE_END_MARKER)
    return "\n".join(lines)


def replace_block(text: str, begin_marker: str, end_marker: str, block: str) -> str:
    pattern = re.compile(
        rf"^{re.escape(begin_marker)}$.*?^{re.escape(end_marker)}$",
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
    if BEGIN_MARKER in original:
        expected = replace_block(original, BEGIN_MARKER, END_MARKER, generate_block())
    elif LITE_BEGIN_MARKER in original:
        expected = replace_block(
            original,
            LITE_BEGIN_MARKER,
            LITE_END_MARKER,
            generate_lite_block(),
        )
    else:
        raise SystemExit("RTLに生成table markerがありません")
    if args.check is not None:
        if original != expected:
            raise SystemExit(f"再生成したsincospi定数がRTLと一致しません: {path}")
        print(f"PASS: {path} のsincospi定数とtableが一致しました")
        return
    path.write_text(expected)
    print(f"updated: {path}")


if __name__ == "__main__":
    main()
