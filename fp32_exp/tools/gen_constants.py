#!/usr/bin/env python3
# Copyright 2026 Ryota Shioya
# SPDX-License-Identifier: Apache-2.0

"""通常方式の定数と2^(j/64) Q30テーブルを100桁精度で再生成する。"""

import argparse
import re
from pathlib import Path

import mpmath as mp


mp.mp.dps = 100  # binary32用係数を十分な余裕で量子化する。


def generated_values() -> tuple[int, int, list[int]]:
    """RTLで使う二つの定数と64要素テーブルを最近傍偶数へ丸める。"""
    inv_ln2_64_q12 = int(mp.nint((64 / mp.log(2)) * (1 << 12)))
    ln2_by_64_q40 = int(mp.nint((mp.log(2) / 64) * (1 << 40)))
    table_q30 = [
        int(mp.nint(mp.power(2, mp.mpf(index) / 64) * (1 << 30)))
        for index in range(64)
    ]
    return inv_ln2_64_q12, ln2_by_64_q40, table_q30


def print_values(inv_q12: int, ln2_q40: int, table_q30: list[int]) -> None:
    """SystemVerilogへ転記できる10進値を表示する。"""
    print(f"INV_LN2_64_Q12 = {inv_q12}")
    print(f"LN2_BY_64_Q40 = {ln2_q40}")
    print("EXP2_TABLE_Q30 = '{")
    for index in range(0, 64, 4):
        suffix = "," if index < 60 else ""
        print(
            "    "
            + ", ".join(f"31'd{value}" for value in table_q30[index:index + 4])
            + suffix
        )
    print("};")


def check_rtl(path: Path, inv_q12: int, ln2_q40: int,
              table_q30: list[int]) -> None:
    """指定RTLから値を抽出し、再生成値との一致を検査する。"""
    text = path.read_text()
    inv_match = re.search(r"INV_LN2_64_Q12\s*=\s*19'd(\d+)", text)
    ln2_match = re.search(r"LN2_BY_64_Q40\s*=\s*35'sd(\d+)", text)
    table_match = re.search(
        r"EXP2_TABLE_Q30\s*\[0:63\]\s*=\s*'\{(.*?)\};",
        text,
        re.DOTALL,
    )
    if inv_match is None or ln2_match is None or table_match is None:
        raise SystemExit(f"RTLから定数またはテーブルを抽出できません: {path}")
    rtl_inv = int(inv_match.group(1))
    rtl_ln2 = int(ln2_match.group(1))
    rtl_table = [int(value) for value in re.findall(r"31'd(\d+)", table_match.group(1))]
    if (rtl_inv, rtl_ln2, rtl_table) != (inv_q12, ln2_q40, table_q30):
        raise SystemExit(f"再生成値がRTLと一致しません: {path}")
    print(f"PASS: {path} の定数2個とテーブル64要素が一致しました")


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
