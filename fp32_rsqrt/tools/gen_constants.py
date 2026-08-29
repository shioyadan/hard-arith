#!/usr/bin/env python3
# Copyright 2026 Ryota Shioya and Toru Koizumi
# SPDX-License-Identifier: Apache-2.0

"""FP32Rsqrtの指数偶奇別32区間初期値を再生成・照合する。"""

import argparse
import re
from decimal import Decimal, ROUND_HALF_EVEN, getcontext
from pathlib import Path


INTERVAL_BITS = 5
INTERVALS = 1 << INTERVAL_BITS
PARITIES = 2
TABLE_FRACTION_BITS = 16
RESIDUAL_BITS = 11
ERROR_WIDTH = 44
ERROR_DROP_BITS = 26
FINAL_FRACTION_BITS = 32
NEWTON_ROUND_BIAS = 128

getcontext().prec = 100


def quantize(value: Decimal, fraction_bits: int) -> int:
    """Decimal値をties-to-evenで固定小数点整数へ量子化する。"""
    scaled = value * Decimal(1 << fraction_bits)
    return int(scaled.to_integral_value(rounding=ROUND_HALF_EVEN))


def centered_line_endpoints(interval: int, parity: int) -> tuple[Decimal, Decimal]:
    """相対誤差を中心化した弦の左右端値を返す。"""
    count = Decimal(INTERVALS)
    left_x = Decimal(1) + Decimal(interval) / count
    right_x = left_x + Decimal(1) / count
    left_root = left_x.sqrt()
    right_root = right_x.sqrt()
    geometric = (left_x * right_x).sqrt()
    maximum_x = (left_x + geometric + right_x) / Decimal(3)
    scale = Decimal(1) if parity == 0 else Decimal(2).sqrt()
    left_y = Decimal(1) / (scale * left_root)
    right_y = Decimal(1) / (scale * right_root)
    chord_at_maximum = left_y + (
        (maximum_x - left_x) * (right_y - left_y)
        / (right_x - left_x)
    )
    exact_at_maximum = Decimal(1) / (scale * maximum_x.sqrt())
    maximum_relative_error = chord_at_maximum / exact_at_maximum - Decimal(1)
    center_scale = Decimal(2) / (Decimal(2) + maximum_relative_error)
    return center_scale * left_y, center_scale * right_y


def generated_values() -> tuple[list[int], list[int], int]:
    """偶奇2通り×32区間のQ16切片・差分と最終biasを返す。"""
    intercepts: list[int] = []
    deltas: list[int] = []
    for parity in range(PARITIES):
        for interval in range(INTERVALS):
            left, right = centered_line_endpoints(interval, parity)
            left_q = quantize(left, TABLE_FRACTION_BITS)
            right_q = quantize(right, TABLE_FRACTION_BITS)
            intercepts.append(left_q)
            deltas.append(left_q - right_q)
    if max(intercepts).bit_length() > 16:
        raise AssertionError("Q16切片が16 bitを超える")
    if max(deltas).bit_length() > 10:
        raise AssertionError("Q16差分が10 bitを超える")
    return intercepts, deltas, NEWTON_ROUND_BIAS


def print_values(intercepts: list[int], deltas: list[int], bias: int) -> None:
    """SystemVerilogへ転記できる定数を表示する。"""
    print("rsqrt_intercept_q16 = '{")
    for index, value in enumerate(intercepts):
        suffix = "," if index != len(intercepts) - 1 else ""
        print(f"    16'h{value:04x}{suffix}")
    print("};")
    print("rsqrt_delta_q16 = '{")
    for index, value in enumerate(deltas):
        suffix = "," if index != len(deltas) - 1 else ""
        print(f"    10'h{value:03x}{suffix}")
    print("};")
    print(f"newton_round_bias = {bias}")


def initial_error_range(
    intercepts: list[int], deltas: list[int]
) -> tuple[int, int]:
    """補間bucketの両端でt*y0^2-1の整数範囲を求める。"""
    minimum: int | None = None
    maximum: int | None = None
    low_bits = 23 - INTERVAL_BITS - RESIDUAL_BITS
    for parity in range(PARITIES):
        for interval in range(INTERVALS):
            table_index = (parity << INTERVAL_BITS) | interval
            for residual in range(1 << RESIDUAL_BITS):
                seed = intercepts[table_index] - (
                    deltas[table_index] * residual >> RESIDUAL_BITS
                )
                for residual_low in (0, (1 << low_bits) - 1):
                    fraction = (
                        (interval << (23 - INTERVAL_BITS))
                        | (residual << low_bits)
                        | residual_low
                    )
                    if parity == 0 and fraction == 0:
                        continue
                    significand = (1 << 23) | fraction
                    product = significand * seed * seed
                    error = (product << parity) - (1 << 55)
                    minimum = error if minimum is None else min(minimum, error)
                    maximum = error if maximum is None else max(maximum, error)
    if minimum is None or maximum is None:
        raise AssertionError("初期誤差範囲を求められない")
    return minimum, maximum


def extract_values(text: str, name: str, width: int) -> list[int]:
    """RTLのlocalparam配列から十六進値を抽出する。"""
    match = re.search(
        rf"{name}\s*\[0:63\]\s*=\s*'\{{(.*?)\}};",
        text,
        re.DOTALL,
    )
    if match is None:
        raise SystemExit(f"RTLから{name}を抽出できません")
    return [
        int(value, 16)
        for value in re.findall(rf"{width}'h([0-9a-fA-F]+)", match.group(1))
    ]


def check_rtl(
    path: Path, intercepts: list[int], deltas: list[int], bias: int
) -> None:
    """RTLの表、主要幅、slice、biasを正式構成と照合する。"""
    text = path.read_text()
    rtl_intercepts = extract_values(text, "rsqrt_intercept_q16", 16)
    rtl_deltas = extract_values(text, "rsqrt_delta_q16", 10)
    if rtl_intercepts != intercepts or rtl_deltas != deltas:
        raise SystemExit(f"再生成した係数がRTLと一致しません: {path}")
    required_patterns = {
        "table index": r"wire\s*\[5:0\]\s+table_index\s*=",
        "residual": r"wire\s*\[10:0\]\s+residual\s*=",
        "seed": r"wire\s*\[15:0\]\s+rsqrt_seed\s*=",
        "seed square": r"wire\s*\[31:0\]\s+seed_square\s*=",
        "seed product": r"wire\s*\[55:0\]\s+seed_product\s*=",
        "modulo error": (
            r"wire\s+signed\s*\[43:0\]\s+error_excess\s*=.*?"
            r"scaled_seed_product\[43:0\]"
        ),
        "error slice": r"error_high\s*=\s*error_excess\[43:26\]",
        "final bias": rf"\+\s*34'sd{bias}\s*;",
    }
    for description, pattern in required_patterns.items():
        if re.search(pattern, text, re.DOTALL) is None:
            raise SystemExit(f"RTLの{description}が正式構成と一致しません: {path}")
    print(
        f"PASS: {path} の64行Q16係数、主要幅・slice、"
        "signed modulo残差、Newton biasが一致しました"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", type=Path)
    parser.add_argument("--analyze", action="store_true")
    args = parser.parse_args()
    intercepts, deltas, bias = generated_values()
    if args.check is not None:
        check_rtl(args.check, intercepts, deltas, bias)
    elif not args.analyze:
        print_values(intercepts, deltas, bias)
    if args.analyze:
        minimum, maximum = initial_error_range(intercepts, deltas)
        print(f"initial_error_min={minimum}")
        print(f"initial_error_max={maximum}")
        print(f"signed_error_bits={max(abs(minimum), abs(maximum)).bit_length() + 1}")
        print(f"configured_error_bits={ERROR_WIDTH}")
        print(f"error_drop_bits={ERROR_DROP_BITS}")
        print(f"final_fraction_bits={FINAL_FRACTION_BITS}")


if __name__ == "__main__":
    main()
