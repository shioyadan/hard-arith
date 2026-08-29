#!/usr/bin/env python3
# Copyright 2026 Ryota Shioya and Toru Koizumi
# SPDX-License-Identifier: Apache-2.0

"""ln(2)定数と調整済みQ26 tableを再生成し、RTLへの転記を照合する。"""

import argparse
import re
from pathlib import Path

import mpmath as mp


mp.mp.dps = 100

# RNE(2^(j/64)*2^26)からの探索済み差分。
TABLE_RNE_DELTAS = (
    4, 5, 5, 5, 5, 5, 5, 4,
    5, 4, 5, 5, 4, 6, 4, 5,
    4, 4, 5, 5, 5, 5, 5, 6,
    6, 5, 5, 5, 5, 5, 5, 4,
    5, 6, 5, 5, 5, 5, 6, 5,
    5, 5, 5, 6, 5, 5, 5, 6,
    6, 6, 5, 5, 6, 6, 6, 5,
    6, 5, 6, 5, 6, 5, 5, 7,
)
COEFFICIENT_UP_MASK = 0x7E9D67157815E428
COEFFICIENT_BIT5_MASK = 0x82F64E5E3B0D227C
COEFFICIENT_ZERO_INDEX = 4


def generated_values() -> tuple[int, list[int], int, int, int]:
    """数式から量子化した定数と探索metadataを返す。"""
    ln2_q21 = int(mp.nint(mp.log(2) * (1 << 21)))
    table_q26 = [
        int(mp.nint(mp.power(2, mp.mpf(index) / 64) * (1 << 26)))
        + TABLE_RNE_DELTAS[index]
        for index in range(64)
    ]
    return (
        ln2_q21,
        table_q26,
        COEFFICIENT_UP_MASK,
        COEFFICIENT_BIT5_MASK,
        COEFFICIENT_ZERO_INDEX,
    )


def print_values(
    ln2_q21: int,
    table_q26: list[int],
    coefficient_up_mask: int,
    coefficient_bit5_mask: int,
    coefficient_zero_index: int,
) -> None:
    """SystemVerilogへ転記できる形式で表示する。"""
    print(f"ln2_q21 = 21'h{ln2_q21:06x}")
    print("exp2_table_q26 = '{")
    for index, value in enumerate(table_q26):
        suffix = "," if index != 63 else ""
        print(f"    27'h{value:07x}{suffix}")
    print("};")
    print(f"coefficient_up_mask = 64'h{coefficient_up_mask:016x}")
    print(f"coefficient_bit5_mask = 64'h{coefficient_bit5_mask:016x}")
    print(f"coefficient_zero_index = {coefficient_zero_index}")


def check_rtl(
    path: Path,
    ln2_q21: int,
    table_q26: list[int],
    coefficient_up_mask: int,
    coefficient_bit5_mask: int,
    coefficient_zero_index: int,
) -> None:
    """RTLから定数を抽出し、再生成値と一致することを確認する。"""
    text = path.read_text()
    ln2_match = re.search(r"ln2_q21\s*=\s*21'h([0-9a-fA-F]+)", text)
    table_match = re.search(
        r"exp2_table_q26\s*\[0:63\]\s*=\s*'\{(.*?)\};",
        text,
        re.DOTALL,
    )
    up_mask_match = re.search(
        r"coefficient_up_mask\s*=\s*64'h([0-9a-fA-F]+)", text)
    bit5_mask_match = re.search(
        r"coefficient_bit5_mask\s*=\s*64'h([0-9a-fA-F]+)", text)
    zero_index_match = re.search(
        r"coefficient_nonzero\s*=\s*j\s*!=\s*6'd([0-9]+)", text)
    if None in (
        ln2_match,
        table_match,
        up_mask_match,
        bit5_mask_match,
        zero_index_match,
    ):
        raise SystemExit(f"RTLから定数またはmetadataを抽出できません: {path}")

    actual = (
        int(ln2_match.group(1), 16),
        [int(value, 16) for value in re.findall(
            r"27'h([0-9a-fA-F]+)", table_match.group(1))],
        int(up_mask_match.group(1), 16),
        int(bit5_mask_match.group(1), 16),
        int(zero_index_match.group(1), 10),
    )
    expected = (
        ln2_q21,
        table_q26,
        coefficient_up_mask,
        coefficient_bit5_mask,
        coefficient_zero_index,
    )
    if actual != expected:
        raise SystemExit(f"再生成値がRTLと一致しません: {path}")
    print(
        f"PASS: {path} のln(2)、table 64要素、mask 2個、"
        "係数例外indexが一致しました"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", type=Path, help="再生成値と照合するRTL")
    args = parser.parse_args()
    values = generated_values()
    if args.check is None:
        print_values(*values)
    else:
        check_rtl(args.check, *values)


if __name__ == "__main__":
    main()
