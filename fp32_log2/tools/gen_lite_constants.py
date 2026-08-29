#!/usr/bin/env python3
# Copyright 2026 Ryota Shioya and Toru Koizumi
# SPDX-License-Identifier: Apache-2.0

"""FP32Log2Liteの64区間Q22二次係数を再生成・照合する。"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import mpmath as mp


INTERVALS = 64
OUTPUT_FRACTION_BITS = 22
BEGIN_MARKER = "// BEGIN GENERATED LOG2 LITE TABLES"
END_MARKER = "// END GENERATED LOG2 LITE TABLES"

# 高精度Taylor係数をRNE量子化した値からの探索済み差分。
# 各区間の全2^17入力について最大絶対誤差と単調性を評価して決めた。
COEFFICIENT_0_DELTAS = (
    0, 1, 1, 0, 1, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 1,
    0, 0, 0, 1, 1, 1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 1,
    0, 0, 1, 1, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0,
    0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 1, 1, 0, 1, 0, 1,
)
COEFFICIENT_1_DELTAS = (
    2, 2, 2, 2, 2, 2, 2, 1, 2, 2, 2, 1, 2, 1, 1, 2,
    1, 1, 1, 2, 1, 1, 1, 2, 1, 1, 1, 1, 1, 1, 1, 1,
    1, 0, 1, 1, 1, 1, 1, 1, 1, 1, 0, 1, 0, 1, 1, 1,
    0, 0, 0, 0, 1, 1, 0, 1, 1, 1, 0, 1, 1, 1, 0, 1,
)
COEFFICIENT_2_DELTAS = (
    0, -1, -1, 3, 0, 3, 2, 2, 0, 0, -1, 2, 2, 1, 2, -1,
    2, 3, 2, 0, -1, 0, 2, 0, 1, 0, 0, 1, 0, 0, 1, -1,
    2, 2, 0, -1, 1, -2, -2, -2, -1, -2, 0, -1, -1, -1, 2, 0,
    1, 1, 1, 0, 1, 2, 4, 4, 5, 0, -2, -2, 3, -2, 1, -5,
)


def quantize(value: mp.mpf) -> int:
    """実数値をties-to-evenで整数化する。"""
    return int(mp.nint(value * (1 << OUTPUT_FRACTION_BITS)))


def generated_values() -> tuple[list[int], list[int], list[int]]:
    """区間中央Taylor係数へ探索済み微調整を適用する。"""
    mp.mp.dps = 100
    coefficient_0: list[int] = []
    coefficient_1: list[int] = []
    coefficient_2: list[int] = []
    for index in range(INTERVALS):
        center = mp.mpf(1) + (mp.mpf(index) + mp.mpf("0.5")) / INTERVALS
        interval_width = mp.mpf(1) / INTERVALS
        coefficient_0.append(
            quantize(mp.log(center, 2)) + COEFFICIENT_0_DELTAS[index]
        )
        coefficient_1.append(
            quantize(interval_width / (center * mp.log(2)))
            + COEFFICIENT_1_DELTAS[index]
        )
        coefficient_2.append(
            quantize(
                -interval_width * interval_width
                / (2 * center * center * mp.log(2))
            )
            + COEFFICIENT_2_DELTAS[index]
        )
    return coefficient_0, coefficient_1, coefficient_2


def signed_literal(width: int, value: int) -> str:
    if value < 0:
        return f"-{width}'sd{-value}"
    return f"{width}'sd{value}"


def table_array(name: str, width: int, values: list[int], signed: bool) -> list[str]:
    qualifier = " signed" if signed else ""
    lines = [
        f"    localparam{qualifier} [{width - 1}:0] {name} [0:63] = '{{"
    ]
    for index, value in enumerate(values):
        comma = "," if index != 63 else ""
        literal = signed_literal(width, value) if signed else f"{width}'d{value}"
        lines.append(f"        {literal}{comma}")
    lines.append("    };")
    return lines


def generate_block() -> str:
    coefficient_0, coefficient_1, coefficient_2 = generated_values()
    if max(coefficient_0).bit_length() > 22:
        raise AssertionError("coefficient_0が22 bitを超える")
    if max(abs(value) for value in coefficient_1).bit_length() + 1 > 18:
        raise AssertionError("coefficient_1がsigned 18 bitを超える")
    if max(abs(value) for value in coefficient_2).bit_length() + 1 > 11:
        raise AssertionError("coefficient_2がsigned 11 bitを超える")

    lines = [
        BEGIN_MARKER,
        "    // 係数はすべて最終和と同じ2^-22単位で格納する。",
        "    // 実値の範囲だけに合わせて22/18/11 bitへ幅を縮めている。",
    ]
    lines.extend(table_array(
        "coefficient_0_table_q22", 22, coefficient_0, False
    ))
    lines.extend(table_array(
        "coefficient_1_table_q22", 18, coefficient_1, True
    ))
    lines.extend(table_array(
        "coefficient_2_table_q22", 11, coefficient_2, True
    ))
    lines.append("")
    lines.append(END_MARKER)
    return "\n".join(lines)


def replace_block(text: str, block: str) -> str:
    pattern = re.compile(
        rf"^    {re.escape(BEGIN_MARKER)}$.*?^    {re.escape(END_MARKER)}$",
        re.MULTILINE | re.DOTALL,
    )
    # RTLではmarker自体をmodule内へ4-space indentしている。
    indented_block = "\n".join(
        ("    " + line) if line.startswith("//") else line
        for line in block.splitlines()
    )
    if pattern.search(text) is None:
        raise SystemExit("RTLにLog2 Lite生成table markerがありません")
    return pattern.sub(indented_block, text)


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
            raise SystemExit(f"再生成したLog2 Lite係数がRTLと一致しません: {path}")
        print(f"PASS: {path} の64区間Q22二次係数が一致しました")
        return
    path.write_text(expected)
    print(f"updated: {path}")


if __name__ == "__main__":
    main()
