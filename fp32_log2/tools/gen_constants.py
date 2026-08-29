#!/usr/bin/env python3
"""FP32Log2のmixed-precision tableを生成・照合する。"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import mpmath as mp


LOG_FRACTION_BITS = 34
A_FRACTION_BITS = 27
B_FRACTION_BITS = 17
C_FRACTION_BITS = 8
TABLE_K = 7
TABLE_MIN_J = -37
TABLE_MAX_J = 53
BEGIN_MARKER = "// BEGIN GENERATED LOG2 TABLES"
END_MARKER = "// END GENERATED LOG2 TABLES"


def round_nearest(value: mp.mpf) -> int:
    """正負対称のround-half-away-from-zeroで整数化する。"""
    if value >= 0:
        return int(mp.floor(value + mp.mpf("0.5")))
    return -int(mp.floor(-value + mp.mpf("0.5")))


def quantize(value: mp.mpf, scale: int) -> int:
    return round_nearest(value * scale)


def signed_literal(width: int, value: int) -> str:
    if value < 0:
        return f"-{width}'sd{-value}"
    return f"{width}'sd{value}"


def table_array(name: str, width: int, values: list[tuple[int, int]]) -> list[str]:
    lines = [
        f"    localparam [{width - 1}:0] {name} [0:{len(values) - 1}] = '{{"
    ]
    for position, (index, value) in enumerate(values):
        comma = "," if position + 1 < len(values) else ""
        lines.append(
            f"        {signed_literal(width, value)}{comma} // j = {index}"
        )
    lines.append("    };")
    return lines


def generate_block() -> str:
    mp.mp.dps = 120
    sqrt2_q23 = int(mp.ceil(mp.sqrt(2) * (1 << 23)))

    table_entries: list[tuple[int, int, int, int, int]] = []
    for j in range(TABLE_MIN_J, TABLE_MAX_J + 1):
        c = 1 + mp.mpf(j) / (1 << TABLE_K)
        table_entries.append(
            (
                j,
                quantize(mp.log(c, 2), 1 << LOG_FRACTION_BITS),
                quantize(1 / (c * mp.log(2)), 1 << A_FRACTION_BITS),
                quantize(-1 / (2 * c * c * mp.log(2)), 1 << B_FRACTION_BITS),
                quantize(1 / (3 * c * c * c * mp.log(2)), 1 << C_FRACTION_BITS),
            )
        )

    lines = [
        BEGIN_MARKER,
        f"    localparam [23:0] sqrt2_q23 = 24'd{sqrt2_q23};",
        "",
    ]
    lines.extend(table_array(
        "logarithm_table_q34",
        35,
        [(index, logarithm) for index, logarithm, _, _, _ in table_entries],
    ))
    lines.append("")
    lines.extend(table_array(
        "coefficient_a_table_q27",
        30,
        [(index, coefficient_a) for index, _, coefficient_a, _, _ in table_entries],
    ))
    lines.append("")
    lines.extend(table_array(
        "coefficient_b_table_q17",
        19,
        [(index, coefficient_b) for index, _, _, coefficient_b, _ in table_entries],
    ))
    lines.append("")
    lines.extend(table_array(
        "coefficient_c_table_q8",
        10,
        [(index, coefficient_c) for index, _, _, _, coefficient_c in table_entries],
    ))
    lines.append(END_MARKER)
    return "\n".join(lines)


def replace_block(text: str, block: str) -> str:
    pattern = re.compile(
        rf"^{re.escape(BEGIN_MARKER)}$.*?^{re.escape(END_MARKER)}$",
        re.MULTILINE | re.DOTALL,
    )
    if pattern.search(text) is None:
        raise SystemExit("RTLに生成テーブルmarkerがありません")
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
            raise SystemExit(f"再生成したlog2定数がRTLと一致しません: {path}")
        print(f"PASS: {path} のlog2定数とtableが一致しました")
        return
    path.write_text(expected)
    print(f"updated: {path}")


if __name__ == "__main__":
    main()
