#!/usr/bin/env python3
# Copyright 2026 Ryota Shioya
# SPDX-License-Identifier: Apache-2.0

"""32区間のcentered Q14初期値を厳密整数演算で再生成・照合する。"""

import argparse
import re
from pathlib import Path


INTERVAL_BITS = 5
INTERVALS = 1 << INTERVAL_BITS
TABLE_FRACTION_BITS = 14
DELTA_DROP_BITS = 1
RESIDUAL_BITS = 11
CORRECTION_SEED_DROP_BITS = 1
ERROR_DROP_BITS = 11
FINAL_FRACTION_BITS = 27
OUTPUT_FRACTION_BITS = 24
INITIAL_TUNE_RADIUS = 1
TABLE_SCALE = 1 << TABLE_FRACTION_BITS
NEWTON_ROUND_BIAS = 4


def round_div(numerator: int, denominator: int) -> int:
    """正の有理数をnearestへ丸める。tieは本生成式では生じない。"""
    return (numerator + denominator // 2) // denominator


def centered_table() -> tuple[list[int], list[int]]:
    """連続minimax直線をQ14/Q13へ量子化した初期表を返す。"""
    intercepts: list[int] = []
    deltas: list[int] = []
    for index in range(INTERVALS):
        left_denominator = INTERVALS + index
        right_denominator = left_denominator + 1
        minimax_denominator = 8 * left_denominator * right_denominator + 1
        # 区間両端の相対誤差-Eと区間内の最大相対誤差+Eを
        # 釣り合わせる連続minimax直線の左右端をQ14へ丸める。
        left = round_div(
            8 * right_denominator * INTERVALS * TABLE_SCALE,
            minimax_denominator,
        )
        right = round_div(
            8 * left_denominator * INTERVALS * TABLE_SCALE,
            minimax_denominator,
        )
        intercepts.append(left)
        deltas.append((left - right) >> DELTA_DROP_BITS)
    return intercepts, deltas


def initial_error_range(
    interval: int, intercept: int, delta: int
) -> tuple[int, int]:
    """一行の量子化区間端でsigned Newton残差の最小・最大を返す。"""
    residual_full_bits = 23 - INTERVAL_BITS
    residual_drop_bits = residual_full_bits - RESIDUAL_BITS
    interpolation_shift = RESIDUAL_BITS - DELTA_DROP_BITS
    product_one = 1 << (23 + TABLE_FRACTION_BITS)
    minimum: int | None = None
    maximum: int | None = None

    for residual in range(1 << RESIDUAL_BITS):
        seed = intercept - ((delta * residual) >> interpolation_shift)
        residual_low = residual << residual_drop_bits
        residual_high = residual_low + (1 << residual_drop_bits) - 1
        for full_residual in (residual_low, residual_high):
            fraction = (interval << residual_full_bits) | full_residual
            if fraction == 0:
                continue
            significand = (1 << 23) | fraction
            error = significand * seed - product_one
            minimum = error if minimum is None else min(minimum, error)
            maximum = error if maximum is None else max(maximum, error)

    if minimum is None or maximum is None:
        raise AssertionError("空の初期誤差区間")
    return minimum, maximum


def tune_initial_error(
    intercepts: list[int], deltas: list[int]
) -> tuple[list[int], list[int]]:
    """各行のsigned初期誤差を0の周囲へ寄せる決定的な局所探索を行う。"""
    tuned_intercepts: list[int] = []
    tuned_deltas: list[int] = []
    for interval, (base_intercept, base_delta) in enumerate(
        zip(intercepts, deltas, strict=True)
    ):
        best_score: int | None = None
        best_span: int | None = None
        best_intercept = base_intercept
        best_delta = base_delta
        # 同点ではoffsetの小さい候補を維持する。この走査順も生成規約の一部。
        for intercept_offset in range(
            -INITIAL_TUNE_RADIUS, INITIAL_TUNE_RADIUS + 1
        ):
            for delta_offset in range(
                -INITIAL_TUNE_RADIUS, INITIAL_TUNE_RADIUS + 1
            ):
                intercept = base_intercept + intercept_offset
                delta = base_delta + delta_offset
                if intercept <= 0 or delta <= 0:
                    continue
                minimum, maximum = initial_error_range(
                    interval, intercept, delta
                )
                score = max(abs(minimum), abs(maximum))
                span = maximum - minimum
                if (
                    best_score is None
                    or score < best_score
                    or (score == best_score and span < best_span)
                ):
                    best_score = score
                    best_span = span
                    best_intercept = intercept
                    best_delta = delta
        tuned_intercepts.append(best_intercept)
        tuned_deltas.append(best_delta)
    return tuned_intercepts, tuned_deltas


def generated_values() -> tuple[list[int], list[int], int]:
    """調整済み32行Q14切片、Q13差分、Newton biasを返す。"""
    intercepts, deltas = centered_table()
    intercepts, deltas = tune_initial_error(intercepts, deltas)
    if len(intercepts) != INTERVALS or len(deltas) != INTERVALS:
        raise AssertionError("テーブル行数が32ではない")
    if max(intercepts).bit_length() > 14 or max(deltas).bit_length() > 8:
        raise AssertionError("生成した係数がRTLの格納幅を超える")
    return intercepts, deltas, NEWTON_ROUND_BIAS


def print_values(
    intercepts: list[int], deltas: list[int], newton_bias: int
) -> None:
    """SystemVerilogへ転記できる係数を表示する。"""
    print("reciprocal_intercept_q14 = '{")
    for index, value in enumerate(intercepts):
        suffix = "," if index != INTERVALS - 1 else ""
        print(f"    14'h{value:04x}{suffix}")
    print("};")
    print("reciprocal_delta_q13 = '{")
    for index, value in enumerate(deltas):
        suffix = "," if index != INTERVALS - 1 else ""
        print(f"    8'h{value:02x}{suffix}")
    print("};")
    print(f"newton_round_bias = {newton_bias}")


def require_rtl_pattern(text: str, description: str, pattern: str) -> None:
    """RTLの幅・bit sliceが正式構成と一致することを確認する。"""
    if re.search(pattern, text, re.DOTALL) is None:
        raise SystemExit(f"RTLの{description}が32区間Q14/Q27構成と一致しません")


def check_rtl(
    path: Path,
    intercepts: list[int],
    deltas: list[int],
    newton_bias: int,
) -> None:
    """RTLの係数表、主要信号幅、bit slice、biasを照合する。"""
    text = path.read_text()
    intercept_match = re.search(
        r"reciprocal_intercept_q14\s*\[0:31\]\s*=\s*'\{(.*?)\};",
        text,
        re.DOTALL,
    )
    delta_match = re.search(
        r"reciprocal_delta_q13\s*\[0:31\]\s*=\s*'\{(.*?)\};",
        text,
        re.DOTALL,
    )
    bias_match = re.search(
        r"reciprocal_q27\s*=.*?\+\s*28'sd([0-9]+)\s*;",
        text,
        re.DOTALL,
    )
    if intercept_match is None or delta_match is None or bias_match is None:
        raise SystemExit(f"RTLから32行係数表またはbiasを抽出できません: {path}")

    rtl_values = (
        [
            int(value, 16)
            for value in re.findall(
                r"14'h([0-9a-fA-F]+)", intercept_match.group(1)
            )
        ],
        [
            int(value, 16)
            for value in re.findall(
                r"8'h([0-9a-fA-F]+)", delta_match.group(1)
            )
        ],
        int(bias_match.group(1)),
    )
    expected_values = (intercepts, deltas, newton_bias)
    if rtl_values != expected_values:
        raise SystemExit(f"再生成値がRTLと一致しません: {path}")

    required_patterns = {
        "interval幅": r"wire\s*\[4:0\]\s+interval\s*=\s*x_mant\[22:18\]",
        "residual幅": r"wire\s*\[10:0\]\s+residual\s*=\s*x_mant\[17:7\]",
        "補間積幅": r"wire\s*\[18:0\]\s+interpolation_product\s*=",
        "補間bit slice": r"wire\s*\[8:0\]\s+interpolation\s*=\s*interpolation_product\[18:10\]",
        "seed幅": r"wire\s*\[13:0\]\s+reciprocal_seed\s*=",
        "seed積幅": r"wire\s*\[37:0\]\s+seed_product\s*=",
        "signed modulo残差": (
            r"wire\s+signed\s*\[25:0\]\s+error_excess\s*=\s*"
            r"\$signed\s*\(\s*seed_product\[25:0\]\s*\)"
        ),
        "補正seed幅": (
            r"wire\s*\[12:0\]\s+correction_seed\s*=\s*"
            r"reciprocal_seed\[13:1\]"
        ),
        "補正error幅": (
            r"wire\s+signed\s*\[14:0\]\s+error_high\s*=\s*"
            r"error_excess\[25:11\]"
        ),
        "補正seed signed幅": r"wire\s+signed\s*\[13:0\]\s+correction_seed_signed\s*=",
        "補正積幅": r"wire\s+signed\s*\[28:0\]\s+correction_product\s*=",
        "補正bit slice": (
            r"wire\s+signed\s*\[15:0\]\s+correction\s*=\s*"
            r"correction_product\[27:12\]"
        ),
        "Newton結果幅": r"wire\s+signed\s*\[27:0\]\s+reciprocal_q27\s*=",
        "最終仮数slice": (
            r"wire\s*\[23:0\]\s+reciprocal_sig\s*=\s*"
            r"reciprocal_q27\[26:3\]"
        ),
    }
    for description, pattern in required_patterns.items():
        require_rtl_pattern(text, description, pattern)

    print(
        f"PASS: {path} の32行Q14/Q13係数、主要幅・slice、"
        "signed modulo残差、Newton biasが一致しました"
    )


def signed_bits(minimum: int, maximum: int) -> int:
    """閉区間を表せる最小の二の補数幅を返す。"""
    width = 1
    while minimum < -(1 << (width - 1)) or maximum >= (1 << (width - 1)):
        width += 1
    return width


def analyze(intercepts: list[int], deltas: list[int], bias: int) -> None:
    """全非零仮数でfaithful性、単調性、誤差、safe biasを調べる。"""
    residual_full_bits = 23 - INTERVAL_BITS
    residual_drop_bits = residual_full_bits - RESIDUAL_BITS
    interpolation_shift = RESIDUAL_BITS - DELTA_DROP_BITS
    product_one = 1 << (23 + TABLE_FRACTION_BITS)
    correction_shift = (
        23 + 2 * TABLE_FRACTION_BITS
        - CORRECTION_SEED_DROP_BITS - ERROR_DROP_BITS
        - FINAL_FRACTION_BITS
    )
    output_shift = FINAL_FRACTION_BITS - OUTPUT_FRACTION_BITS
    output_unit = 1 << output_shift
    quotient_numerator = 1 << 47

    previous = 1 << 24
    faithful_failures = 0
    monotonicity_violations = 0
    correct_matches = 0
    safe_bias_low = -(1 << 62)
    safe_bias_high = 1 << 62
    minimum_error = 1 << 62
    maximum_error = -(1 << 62)
    minimum_error_high = 1 << 62
    maximum_error_high = -(1 << 62)
    minimum_correction = 1 << 62
    maximum_correction = -(1 << 62)
    minimum_correction_product = 1 << 62
    maximum_correction_product = -(1 << 62)
    maximum_seed = 0
    maximum_error_numerator = 0
    maximum_error_denominator = 1
    maximum_error_fraction = 0

    for fraction in range(1, 1 << 23):
        interval = fraction >> residual_full_bits
        residual_full = fraction & ((1 << residual_full_bits) - 1)
        residual = residual_full >> residual_drop_bits
        interpolation = deltas[interval] * residual >> interpolation_shift
        seed = intercepts[interval] - interpolation
        significand = (1 << 23) | fraction
        error = significand * seed - product_one
        error_high = error >> ERROR_DROP_BITS
        correction_seed = seed >> CORRECTION_SEED_DROP_BITS
        correction_product = correction_seed * error_high
        correction = correction_product >> correction_shift
        reciprocal_unbiased = (
            seed << (FINAL_FRACTION_BITS - TABLE_FRACTION_BITS)
        ) - correction
        reciprocal_q27 = reciprocal_unbiased + bias
        result = reciprocal_q27 >> output_shift

        lower, remainder = divmod(quotient_numerator, significand)
        upper = lower + (remainder != 0)
        safe_bias_low = max(
            safe_bias_low, lower * output_unit - reciprocal_unbiased
        )
        safe_bias_high = min(
            safe_bias_high,
            (upper + 1) * output_unit - 1 - reciprocal_unbiased,
        )
        if result != lower and result != upper:
            faithful_failures += 1
        if result > previous:
            monotonicity_violations += 1
        previous = result

        rounded = lower + (
            2 * remainder > significand
            or (2 * remainder == significand and (lower & 1) != 0)
        )
        correct_matches += result == rounded
        minimum_error = min(minimum_error, error)
        maximum_error = max(maximum_error, error)
        minimum_error_high = min(minimum_error_high, error_high)
        maximum_error_high = max(maximum_error_high, error_high)
        minimum_correction = min(minimum_correction, correction)
        maximum_correction = max(maximum_correction, correction)
        minimum_correction_product = min(
            minimum_correction_product, correction_product
        )
        maximum_correction_product = max(
            maximum_correction_product, correction_product
        )
        maximum_seed = max(maximum_seed, seed)

        absolute_error_numerator = abs(
            result * significand - quotient_numerator
        )
        if (
            absolute_error_numerator * maximum_error_denominator
            > maximum_error_numerator * significand
        ):
            maximum_error_numerator = absolute_error_numerator
            maximum_error_denominator = significand
            maximum_error_fraction = fraction

    print(f"checked_nonzero_significands={(1 << 23) - 1}")
    print(f"faithful_failures={faithful_failures}")
    print(f"monotonicity_violations={monotonicity_violations}")
    print(f"correct_matches={correct_matches}")
    print(f"safe_bias_low={safe_bias_low}")
    print(f"safe_bias_high={safe_bias_high}")
    print(f"minimum_error_excess={minimum_error}")
    print(f"maximum_error_excess={maximum_error}")
    print(f"minimum_error_high={minimum_error_high}")
    print(f"maximum_error_high={maximum_error_high}")
    print(f"minimum_correction={minimum_correction}")
    print(f"maximum_correction={maximum_correction}")
    print(f"intercept_bits={max(intercepts).bit_length()}")
    print(f"delta_bits={max(deltas).bit_length()}")
    print(f"seed_bits={maximum_seed.bit_length()}")
    print(
        "correction_seed_bits="
        f"{(maximum_seed >> CORRECTION_SEED_DROP_BITS).bit_length()}"
    )
    print(
        "error_excess_signed_bits="
        f"{signed_bits(minimum_error, maximum_error)}"
    )
    print(
        "error_high_signed_bits="
        f"{signed_bits(minimum_error_high, maximum_error_high)}"
    )
    print(
        "correction_product_signed_bits="
        f"{signed_bits(minimum_correction_product, maximum_correction_product)}"
    )
    print(
        "correction_signed_bits="
        f"{signed_bits(minimum_correction, maximum_correction)}"
    )
    print(
        "maximum_absolute_ulp="
        f"{maximum_error_numerator / maximum_error_denominator:.12f}"
    )
    print(f"maximum_error_fraction=0x{maximum_error_fraction:06x}")
    print(
        "pass="
        f"{int(faithful_failures == 0 and monotonicity_violations == 0)}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", type=Path, help="再生成値と照合するRTL")
    parser.add_argument(
        "--analyze", action="store_true", help="全非零仮数を厳密整数解析する"
    )
    args = parser.parse_args()
    values = generated_values()
    if args.check is None:
        print_values(*values)
    else:
        check_rtl(args.check, *values)
    if args.analyze:
        analyze(*values)


if __name__ == "__main__":
    main()
