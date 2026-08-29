#!/usr/bin/env python3
# Copyright 2026 Ryota Shioya and Toru Koizumi
# SPDX-License-Identifier: Apache-2.0

"""FP32Sqrtの二初期値用接線係数を再生成・照合する。"""

import argparse
import re
from decimal import Decimal, ROUND_HALF_EVEN, getcontext
from pathlib import Path


INTERVAL_BITS = 4
INTERVALS = 1 << INTERVAL_BITS
PARITIES = 2
TABLE_FRACTION_BITS = 16
FINAL_BIAS = 23068672

getcontext().prec = 100


def quantize(value: Decimal) -> int:
    """実数値をQ16へties-to-evenで量子化する。"""
    scaled = value * Decimal(1 << TABLE_FRACTION_BITS)
    return int(scaled.to_integral_value(rounding=ROUND_HALF_EVEN))


def tangent_endpoints(
    interval: int, parity: int, reciprocal: bool
) -> tuple[Decimal, Decimal]:
    """区間中央におけるsqrtまたはinvsqrt接線の左右端値を返す。"""
    left_x = Decimal(1) + Decimal(interval) / Decimal(INTERVALS)
    center_x = left_x + Decimal(1) / Decimal(2 * INTERVALS)
    half_width = Decimal(1) / Decimal(2 * INTERVALS)
    root = center_x.sqrt()
    parity_scale = Decimal(2).sqrt() ** parity
    if reciprocal:
        center_y = Decimal(1) / (parity_scale * root)
        derivative = -Decimal(1) / (
            Decimal(2) * parity_scale * center_x * root
        )
    else:
        center_y = parity_scale * root
        derivative = parity_scale / (Decimal(2) * root)
    return (
        center_y - derivative * half_width,
        center_y + derivative * half_width,
    )


def generated_values() -> tuple[list[int], list[int], list[int], list[int]]:
    """指数偶奇2通り×16区間のQ16切片と差分を返す。"""
    sqrt_intercepts: list[int] = []
    sqrt_deltas: list[int] = []
    invsqrt_intercepts: list[int] = []
    invsqrt_deltas: list[int] = []
    for parity in range(PARITIES):
        for interval in range(INTERVALS):
            left, right = tangent_endpoints(interval, parity, False)
            sqrt_intercepts.append(quantize(left))
            sqrt_deltas.append(quantize(right - left))
            left, right = tangent_endpoints(interval, parity, True)
            invsqrt_intercepts.append(quantize(left))
            invsqrt_deltas.append(quantize(left - right))
    if max(sqrt_intercepts).bit_length() > 17:
        raise AssertionError("sqrt Q16切片が17 bitを超える")
    if max(sqrt_deltas).bit_length() > 12:
        raise AssertionError("sqrt Q16差分が12 bitを超える")
    if max(invsqrt_intercepts).bit_length() > 16:
        raise AssertionError("invsqrt Q16切片が16 bitを超える")
    if max(invsqrt_deltas).bit_length() > 11:
        raise AssertionError("invsqrt Q16差分が11 bitを超える")
    return (
        sqrt_intercepts,
        sqrt_deltas,
        invsqrt_intercepts,
        invsqrt_deltas,
    )


def print_array(name: str, width: int, values: list[int]) -> None:
    """SystemVerilogへ転記できる配列を表示する。"""
    digits = (width + 3) // 4
    print(f"{name} = '{{")
    for index, value in enumerate(values):
        suffix = "," if index != len(values) - 1 else ""
        print(f"    {width}'h{value:0{digits}x}{suffix}")
    print("};")


def extract_values(text: str, name: str, width: int) -> list[int]:
    """RTLのlocalparam配列から十六進値を抽出する。"""
    match = re.search(
        rf"{name}\s*\[0:31\]\s*=\s*'\{{(.*?)\}};",
        text,
        re.DOTALL,
    )
    if match is None:
        raise SystemExit(f"RTLから{name}を抽出できません")
    return [
        int(value, 16)
        for value in re.findall(rf"{width}'h([0-9a-fA-F]+)", match.group(1))
    ]


def check_rtl(path: Path, generated: tuple[list[int], ...]) -> None:
    """RTLの係数、主要幅、slice、最終biasを正式構成と照合する。"""
    text = path.read_text()
    specifications = (
        ("sqrt_intercept_q16", 17, generated[0]),
        ("sqrt_delta_q16", 12, generated[1]),
        ("invsqrt_intercept_q16", 16, generated[2]),
        ("invsqrt_delta_q16", 11, generated[3]),
    )
    for name, width, values in specifications:
        if extract_values(text, name, width) != values:
            raise SystemExit(f"再生成した{name}がRTLと一致しません: {path}")
    required_patterns = {
        "table index": r"wire\s*\[4:0\]\s+table_index\s*=",
        "sqrt residual": r"wire\s*\[7:0\]\s+residual\s*=",
        "invsqrt residual": r"wire\s*\[6:0\]\s+invsqrt_residual\s*=",
        "sqrt seed": r"wire\s*\[17:0\]\s+sqrt_seed\s*=",
        "invsqrt seed": r"wire\s*\[13:0\]\s+invsqrt_seed_q14\s*=",
        "error width": r"wire\s+signed\s*\[23:0\]\s+error_q32\s*=",
        "error slice": r"error_high\s*=\s*error_q32\[23:7\]",
        "final bias": rf"\+\s*52'sd{FINAL_BIAS}\s*;",
    }
    for description, pattern in required_patterns.items():
        if re.search(pattern, text, re.DOTALL) is None:
            raise SystemExit(f"RTLの{description}が正式構成と一致しません: {path}")
    print(
        f"PASS: {path} の32行sqrt／invsqrt Q16係数、"
        "主要幅・slice、最終biasが一致しました"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", type=Path)
    args = parser.parse_args()
    values = generated_values()
    if args.check is not None:
        check_rtl(args.check, values)
        return
    print_array("sqrt_intercept_q16", 17, values[0])
    print_array("sqrt_delta_q16", 12, values[1])
    print_array("invsqrt_intercept_q16", 16, values[2])
    print_array("invsqrt_delta_q16", 11, values[3])
    print(f"final_bias = {FINAL_BIAS}")


if __name__ == "__main__":
    main()
