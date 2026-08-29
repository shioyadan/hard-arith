#!/usr/bin/env python3
# Copyright 2026 Ryota Shioya and Toru Koizumi
# SPDX-License-Identifier: Apache-2.0

"""32区間のQ14切片と7-bit二bank傾きを再生成・照合する。"""

import argparse
import re
from pathlib import Path


INTERVAL_BITS = 5
INTERVALS = 1 << INTERVAL_BITS
TABLE_FRACTION_BITS = 14
DELTA_DROP_BITS = 1
COEFFICIENT_TUNE_RESIDUAL_BITS = 11
RESIDUAL_BITS = 10
DELTA_ENCODED_BITS = 7
DELTA_Q12_INTERVALS = 13
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


def round_shift_ties_even(value: int, shift: int) -> int:
    """非負整数を2^shiftで割り、tie-to-evenで丸める。"""
    if shift == 0:
        return value
    quotient, remainder = divmod(value, 1 << shift)
    halfway = 1 << (shift - 1)
    round_up = remainder > halfway or (
        remainder == halfway and (quotient & 1) != 0
    )
    return quotient + int(round_up)


def delta_scale_shift(interval: int) -> int:
    """7-bit傾きをQ12として使う区間では1、Q13では0を返す。"""
    return int(interval < DELTA_Q12_INTERVALS)


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
    interval: int,
    intercept: int,
    delta: int,
    residual_bits: int,
    scale_shift: int,
) -> tuple[int, int]:
    """一行の量子化区間端でsigned Newton残差の最小・最大を返す。"""
    residual_full_bits = 23 - INTERVAL_BITS
    residual_drop_bits = residual_full_bits - residual_bits
    interpolation_shift = residual_bits - DELTA_DROP_BITS - scale_shift
    product_one = 1 << (23 + TABLE_FRACTION_BITS)
    minimum: int | None = None
    maximum: int | None = None

    for residual in range(1 << residual_bits):
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
                    interval,
                    intercept,
                    delta,
                    COEFFICIENT_TUNE_RESIDUAL_BITS,
                    0,
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


def tune_scaled_table(
    base_intercepts: list[int], base_deltas: list[int]
) -> tuple[list[int], list[int]]:
    """Q12/Q13二bankの7-bit傾きとQ14切片を決定的に局所調整する。"""
    tuned_intercepts: list[int] = []
    tuned_deltas: list[int] = []
    maximum_delta = (1 << DELTA_ENCODED_BITS) - 1
    for interval, (base_intercept, base_delta) in enumerate(
        zip(base_intercepts, base_deltas, strict=True)
    ):
        scale_shift = delta_scale_shift(interval)
        center_delta = round_shift_ties_even(base_delta, scale_shift)
        best_key: tuple[int, int, int, int] | None = None
        best_intercept = base_intercept
        best_delta = center_delta
        for intercept_offset in range(-3, 4):
            for delta_offset in range(-2, 3):
                intercept = base_intercept + intercept_offset
                delta = center_delta + delta_offset
                if not (0 < intercept < TABLE_SCALE):
                    continue
                if not (0 < delta <= maximum_delta):
                    continue
                minimum, maximum = initial_error_range(
                    interval,
                    intercept,
                    delta,
                    # 検証済み係数は11-bit bucketで調整し、その後RTLの
                    # residualだけを10 bitへ縮めた探索順を再現する。
                    COEFFICIENT_TUNE_RESIDUAL_BITS,
                    scale_shift,
                )
                key = (
                    max(abs(minimum), abs(maximum)),
                    maximum - minimum,
                    abs(intercept_offset) + abs(delta_offset),
                    delta,
                )
                if best_key is None or key < best_key:
                    best_key = key
                    best_intercept = intercept
                    best_delta = delta
        if best_key is None:
            raise AssertionError(f"区間{interval}の7-bit係数を生成できません")
        tuned_intercepts.append(best_intercept)
        tuned_deltas.append(best_delta)
    return tuned_intercepts, tuned_deltas


def generated_values() -> tuple[list[int], list[int], int]:
    """調整済み32行Q14切片、7-bit二bank傾き、Newton biasを返す。"""
    intercepts, deltas = centered_table()
    intercepts, deltas = tune_initial_error(intercepts, deltas)
    expected_scale_shifts = [int(delta > 127) for delta in deltas]
    if expected_scale_shifts != [1] * DELTA_Q12_INTERVALS + [0] * (
        INTERVALS - DELTA_Q12_INTERVALS
    ):
        raise AssertionError("Q12/Q13 bank境界が区間12と13の間にありません")
    intercepts, deltas = tune_scaled_table(intercepts, deltas)
    if len(intercepts) != INTERVALS or len(deltas) != INTERVALS:
        raise AssertionError("テーブル行数が32ではない")
    if min(intercepts) < (1 << 13) or max(intercepts).bit_length() > 14:
        raise AssertionError("生成した切片の共通MSBが1ではない")
    if max(deltas).bit_length() > DELTA_ENCODED_BITS:
        raise AssertionError("生成した係数がRTLの格納幅を超える")
    minimum_seed = TABLE_SCALE
    maximum_seed = 0
    for interval in range(INTERVALS):
        shift = RESIDUAL_BITS - DELTA_DROP_BITS - delta_scale_shift(interval)
        for residual in range(1 << RESIDUAL_BITS):
            seed = intercepts[interval] - (
                (deltas[interval] * residual) >> shift
            )
            minimum_seed = min(minimum_seed, seed)
            maximum_seed = max(maximum_seed, seed)
    if minimum_seed < (1 << 13) or maximum_seed >= (1 << 14):
        raise AssertionError(
            f"補間後seedの共通MSBが1ではありません: "
            f"{minimum_seed}..{maximum_seed}"
        )
    return intercepts, deltas, NEWTON_ROUND_BIAS


def print_values(
    intercepts: list[int], deltas: list[int], newton_bias: int
) -> None:
    """SystemVerilogへ転記できる係数を表示する。"""
    print("reciprocal_intercept_low_q14 = '{")
    for index, value in enumerate(intercepts):
        suffix = "," if index != INTERVALS - 1 else ""
        print(f"    13'h{value & 0x1fff:04x}{suffix}")
    print("};")
    print("reciprocal_delta_scaled = '{")
    for index, value in enumerate(deltas):
        suffix = "," if index != INTERVALS - 1 else ""
        print(f"    7'h{value:02x}{suffix}")
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
        r"reciprocal_intercept_low_q14\s*\[0:31\]\s*=\s*'\{(.*?)\};",
        text,
        re.DOTALL,
    )
    delta_match = re.search(
        r"reciprocal_delta_scaled\s*\[0:31\]\s*=\s*'\{(.*?)\};",
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
            (1 << 13) | int(value, 16)
            for value in re.findall(
                r"13'h([0-9a-fA-F]+)", intercept_match.group(1)
            )
        ],
        [
            int(value, 16)
            for value in re.findall(
                r"7'h([0-9a-fA-F]+)", delta_match.group(1)
            )
        ],
        int(bias_match.group(1)),
    )
    expected_values = (intercepts, deltas, newton_bias)
    if rtl_values != expected_values:
        raise SystemExit(f"再生成値がRTLと一致しません: {path}")

    required_patterns = {
        "interval幅": r"wire\s*\[4:0\]\s+interval\s*=\s*x_mant\[22:18\]",
        "residual幅": r"wire\s*\[9:0\]\s+residual\s*=\s*x_mant\[17:8\]",
        "補間積幅": r"wire\s*\[16:0\]\s+interpolation_product\s*=",
        "傾きbank境界": r"wire\s+delta_q12_bank\s*=\s*interval\s*<=\s*5'd12",
        "補間bit slice": (
            r"wire\s*\[8:0\]\s+interpolation\s*=\s*delta_q12_bank\s*"
            r"\?\s*interpolation_product\[16:8\]\s*"
            r":\s*\{\s*1'b0\s*,\s*interpolation_product\[16:9\]\s*\}"
        ),
        "seed下位幅": r"wire\s*\[12:0\]\s+reciprocal_seed_low\s*=",
        "seed MSB復元": (
            r"wire\s*\[13:0\]\s+reciprocal_seed\s*=\s*"
            r"\{\s*1'b1\s*,\s*reciprocal_seed_low\s*\}"
        ),
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
        "仮数zero共有": r"wire\s+x_mant_zero\s*=\s*~\|x_mant",
        "指数減算共有": (
            r"wire\s*\[7:0\]\s+finite_expo\s*=\s*"
            r"8'd253\s*-\s*x_expo\s*\+\s*"
            r"\{\s*7'b0\s*,\s*x_mant_zero\s*\}"
        ),
        "指数全1 decode共有": r"wire\s+x_expo_all_one\s*=\s*&x_expo",
        "指数zero decode共有": r"wire\s+x_expo_zero\s*=\s*~\|x_expo",
    }
    for description, pattern in required_patterns.items():
        require_rtl_pattern(text, description, pattern)

    print(
        f"PASS: {path} の32行Q14/Q12-Q13係数、主要幅・slice、"
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
    minimum_seed = 1 << 62
    maximum_seed = 0
    maximum_error_numerator = 0
    maximum_error_denominator = 1
    maximum_error_fraction = 0

    for fraction in range(1, 1 << 23):
        interval = fraction >> residual_full_bits
        residual_full = fraction & ((1 << residual_full_bits) - 1)
        residual = residual_full >> residual_drop_bits
        interpolation_shift = (
            RESIDUAL_BITS - DELTA_DROP_BITS - delta_scale_shift(interval)
        )
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
        minimum_seed = min(minimum_seed, seed)
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
    print(f"minimum_seed={minimum_seed}")
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
    required_ranges = {
        "seed": ((1 << 13) <= minimum_seed and maximum_seed < (1 << 14)),
        "error_excess": signed_bits(minimum_error, maximum_error) <= 26,
        "error_high": signed_bits(minimum_error_high, maximum_error_high) <= 15,
        "correction_product": (
            signed_bits(minimum_correction_product, maximum_correction_product)
            <= 29
        ),
        "correction": signed_bits(minimum_correction, maximum_correction) <= 16,
        "safe_bias": safe_bias_low <= bias <= safe_bias_high,
        "faithful": faithful_failures == 0,
        "monotonic": monotonicity_violations == 0,
    }
    failed_ranges = [name for name, passed in required_ranges.items() if not passed]
    print(f"pass={int(not failed_ranges)}")
    if failed_ranges:
        raise SystemExit("範囲・精度検査に失敗しました: " + ", ".join(failed_ranges))


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
