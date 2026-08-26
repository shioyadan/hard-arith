#!/usr/bin/env python3
# Copyright 2026 Ryota Shioya and Toru Koizumi
# SPDX-License-Identifier: Apache-2.0

"""引数削減定数と、調整済みQ26テーブルの基準値を再生成・照合する。"""

import argparse
import re
from pathlib import Path

import mpmath as mp


mp.mp.dps = 100  # binary32用定数を十分な余裕で量子化する。

# 各table行はRNE(2^(j/64)*2^26)へ探索済みの整数deltaを加えた値である。
# deltaには近似・積の切り捨て誤差、最終丸めの注入分、単調性調整が含まれる。
TABLE_RNE_DELTAS = (
    4, 5, 5, 5, 5, 5, 5, 4,
    5, 4, 5, 5, 4, 6, 5, 5,
    4, 4, 5, 5, 5, 5, 5, 6,
    6, 5, 5, 5, 5, 5, 5, 4,
    5, 6, 5, 5, 5, 5, 6, 5,
    5, 5, 5, 6, 5, 5, 5, 6,
    6, 6, 5, 5, 6, 6, 6, 5,
    6, 5, 6, 5, 6, 5, 5, 7,
)

# coefficient探索で得たrow別metadata。RTLではtable上位bitと組み合わせる。
# j=4だけは単調性のため通常のepsilonを1から0へ下げる。
COEFFICIENT_UP_MASK = 0x7E9D67157815E428
COEFFICIENT_BIT5_MASK = 0x82F64E5E3B0D227C
COEFFICIENT_ZERO_INDEX = 4


def generated_values() -> tuple[int, int, list[int], int, int, int]:
    """数式から作る定数と、探索deltaを反映したtable値を返す。"""
    inv_ln2_64_q8 = int(mp.nint((64 / mp.log(2)) * (1 << 8)))
    ln2_by_64_q27 = int(mp.nint((mp.log(2) / 64) * (1 << 27)))
    table_q26 = [
        int(mp.nint(mp.power(2, mp.mpf(index) / 64) * (1 << 26)))
        + TABLE_RNE_DELTAS[index]
        for index in range(64)
    ]
    return (
        inv_ln2_64_q8,
        ln2_by_64_q27,
        table_q26,
        COEFFICIENT_UP_MASK,
        COEFFICIENT_BIT5_MASK,
        COEFFICIENT_ZERO_INDEX,
    )


def print_values(
    inv_q8: int,
    ln2_q27: int,
    table_q26: list[int],
    coefficient_up_mask: int,
    coefficient_bit5_mask: int,
    coefficient_zero_index: int,
) -> None:
    """SystemVerilogへ転記できる16進値とtableの実際の補正量を表示する。"""
    print(f"inv_ln2_64_q8 = 15'h{inv_q8:04x}")
    print(f"ln2_by_64_q27 = 21'h{ln2_q27:06x}")
    print("exp2_table_q26 = '{")
    for index, value in enumerate(table_q26):
        exact = mp.power(2, mp.mpf(index) / 64) * (1 << 26)
        offset = float(mp.mpf(value) - exact)
        suffix = "," if index != 63 else ""
        separator = " " if suffix else "  "
        print(
            f"    27'h{value:07x}{suffix}{separator}"
            f"// 2^({index:2d}/64)*2^26 + {offset:.2f}"
        )
    print("};")
    print(f"coefficient_up_mask = 64'h{coefficient_up_mask:016x}")
    print(f"coefficient_bit5_mask = 64'h{coefficient_bit5_mask:016x}")
    print(f"coefficient_zero_index = {coefficient_zero_index}")


def check_rtl(
    path: Path,
    inv_q8: int,
    ln2_q27: int,
    table_q26: list[int],
    coefficient_up_mask: int,
    coefficient_bit5_mask: int,
    coefficient_zero_index: int,
) -> None:
    """指定RTLから定数を抽出し、数式と探索metadataからの再生成値に照合する。"""
    text = path.read_text()
    inv_match = re.search(
        r"inv_ln2_64_q8\s*=\s*15'h([0-9a-fA-F]+)", text)
    ln2_match = re.search(
        r"ln2_by_64_q27\s*=\s*21'h([0-9a-fA-F]+)", text)
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
    if (
        inv_match is None
        or ln2_match is None
        or table_match is None
        or up_mask_match is None
        or bit5_mask_match is None
        or zero_index_match is None
    ):
        raise SystemExit(
            f"RTLから定数、table、mask、または係数例外indexを抽出できません: {path}"
        )

    rtl_values = (
        int(inv_match.group(1), 16),
        int(ln2_match.group(1), 16),
        [int(value, 16) for value in re.findall(
            r"27'h([0-9a-fA-F]+)", table_match.group(1))],
        int(up_mask_match.group(1), 16),
        int(bit5_mask_match.group(1), 16),
        int(zero_index_match.group(1), 10),
    )
    expected_values = (
        inv_q8,
        ln2_q27,
        table_q26,
        coefficient_up_mask,
        coefficient_bit5_mask,
        coefficient_zero_index,
    )
    if rtl_values != expected_values:
        raise SystemExit(f"再生成値がRTLと一致しません: {path}")
    print(
        f"PASS: {path} の定数2個、table 64要素、mask 2個、"
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
