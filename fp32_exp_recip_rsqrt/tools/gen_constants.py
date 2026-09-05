#!/usr/bin/env python3
# Copyright 2026 Ryota Shioya and Toru Koizumi
# SPDX-License-Identifier: Apache-2.0

"""FP32ExpRecipRsqrtの近似係数tableを再生成・照合する。"""

from __future__ import annotations

import argparse
import importlib.util
import math
from pathlib import Path
import re

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = Path(__file__).resolve().parents[1]
TARGET = PACKAGE_DIR / "fp32_exp_recip_rsqrt.sv"
ELEMENTARY_RTL = ROOT / "fp32_elementary/fp32_elementary.sv"
ELEMENTARY_GENERATOR = ROOT / "fp32_elementary/tools/gen_constants.py"
EXP_C0_BIAS_7_INDICES = {21, 41, 50}
EXP_C0_BIAS_BY_INDEX = {10: 9, 55: 9, 58: 10}
EXP_DELTA_MIN = -105264
EXP_DELTA_MAX = 105264
ROOT_DELTA_MIN = -(1 << 16)
ROOT_DELTA_MAX = (1 << 16)-2

COEFFICIENT_BLOCK = re.compile(
    r"    localparam [^\n]* exp_c0_q27_prefix = .*?"
    r"    localparam [^\n]* rsqrt_scaled_c2_q8_suffix \[0:127\] = '\{\n"
    r".*?\n    \};",
    re.DOTALL,
)


def load_elementary_generator():
    spec = importlib.util.spec_from_file_location(
        "fp32_elementary_gen_constants", ELEMENTARY_GENERATOR
    )
    if spec is None or spec.loader is None:
        raise SystemExit("FP32Elementaryの係数generatorを読み込めません")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def array_block(text: str, name: str) -> str:
    pattern = re.compile(
        rf"    localparam [^\n]* {re.escape(name)}_prefix = [^\n]*;\n"
        rf"    localparam [^\n]* {re.escape(name)}_suffix [^\n]*\n.*?\n    \}};",
        re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        raise SystemExit(f"FP32Elementaryから{name}を抽出できません")
    return match.group(0)


def suffix_array_block(text: str, name: str) -> str:
    pattern = re.compile(
        rf"    localparam [^\n]* {re.escape(name)}_suffix [^\n]*\n"
        rf".*?\n    \}};",
        re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        raise SystemExit(f"FP32Elementaryから{name}を抽出できません")
    return match.group(0)


def decode_compressed_array(text: str, name: str) -> list[int]:
    prefix_match = re.search(
        rf"localparam \[(\d+):0\] {re.escape(name)}_prefix = "
        rf"(\d+)'b([01]+);",
        text,
    )
    suffix_match = re.search(
        rf"localparam \[(\d+):0\] {re.escape(name)}_suffix \[0:(\d+)\] = '\{{"
        rf"(.*?)\n    \}};",
        text,
        re.DOTALL,
    )
    if prefix_match is None or suffix_match is None:
        raise SystemExit(f"{name}の圧縮tableを抽出できません")
    prefix_width = int(prefix_match.group(1))+1
    suffix_width = int(suffix_match.group(1))+1
    prefix = int(prefix_match.group(3), 2)
    suffixes = [int(value) for value in re.findall(
        rf"{suffix_width}'d(\d+)", suffix_match.group(3)
    )]
    expected_count = int(suffix_match.group(2))+1
    if len(suffixes) != expected_count:
        raise SystemExit(
            f"{name}の行数が一致しません: {len(suffixes)} != {expected_count}"
        )
    width = prefix_width+suffix_width
    values = []
    for suffix in suffixes:
        value = (prefix << suffix_width) | suffix
        if value & (1 << (width-1)):
            value -= 1 << width
        values.append(value)
    return values


def reconstruction_masks(exp_rows) -> tuple[int, int]:
    c1_epsilon2_mask = 0
    c2_epsilon1_mask = 0
    for index, (c0, c1, c2, _) in enumerate(exp_rows):
        c1_base = c0 >> 10
        c1_epsilon = c1-c1_base
        if c1_epsilon not in (1, 2):
            raise SystemExit(
                f"exp C1 row {index}をC0から再構成できません: eps={c1_epsilon}"
            )
        c1_low_sum = (c1_base & 0x1f)+c1_epsilon
        if (c1_base & 0x20) and (c1_low_sum & 0x20):
            raise SystemExit(f"exp C1 row {index}でbit 6へのcarryが発生します")
        reconstructed_c1 = (
            (c1_base & ~0x3f)
            | (((c1_base >> 5) | (c1_low_sum >> 5)) & 1) << 5
            | (c1_low_sum & 0x1f)
        )
        if reconstructed_c1 != c1:
            raise SystemExit(f"exp C1 row {index}の再構成値が一致しません")
        if c1_epsilon == 2:
            c1_epsilon2_mask |= 1 << index

        c2_base = c0 >> 19
        c2_epsilon = c2-c2_base
        if c2_epsilon not in (0, 1):
            raise SystemExit(
                f"exp C2 row {index}をC0から再構成できません: eps={c2_epsilon}"
            )
        c2_low_sum = (c2_base & 0x1f)+c2_epsilon
        if (c2_base & 0x20) and (c2_low_sum & 0x20):
            raise SystemExit(f"exp C2 row {index}でbit 6へのcarryが発生します")
        reconstructed_c2 = (
            (c2_base & ~0x3f)
            | (((c2_base >> 5) | (c2_low_sum >> 5)) & 1) << 5
            | (c2_low_sum & 0x1f)
        )
        if reconstructed_c2 != c2:
            raise SystemExit(f"exp C2 row {index}の再構成値が一致しません")
        if c2_epsilon == 1:
            c2_epsilon1_mask |= 1 << index
    return c1_epsilon2_mask, c2_epsilon1_mask


def require_range(name: str, values, width: int, signed: bool = True) -> None:
    minimum = int(np.min(values))
    maximum = int(np.max(values))
    if signed:
        lower = -(1 << (width-1))
        upper = (1 << (width-1))-1
    else:
        lower = 0
        upper = (1 << width)-1
    if minimum < lower or maximum > upper:
        raise SystemExit(
            f"{name}が{width}-bit範囲を超えます: "
            f"[{minimum}, {maximum}] not in [{lower}, {upper}]"
        )


def validate_shared_datapath(exp_rows, elementary_text: str) -> None:
    root_banks = []
    for prefix in ("reciprocal", "rsqrt_base", "rsqrt_scaled"):
        c0 = decode_compressed_array(elementary_text, f"{prefix}_c0_q25")
        c1 = decode_compressed_array(elementary_text, f"{prefix}_c1_q17")
        c2 = decode_compressed_array(elementary_text, f"{prefix}_c2_q8")
        root_banks.append((prefix, [
            (row_c0 << 2, row_c1 << 1, row_c2 << 1)
            for row_c0, row_c1, row_c2 in zip(c0, c1, c2)
        ], ROOT_DELTA_MIN, ROOT_DELTA_MAX))

    banks = [
        ("exp", [(c0, c1 << 1, c2) for c0, c1, c2, _ in exp_rows],
         EXP_DELTA_MIN, EXP_DELTA_MAX),
        *root_banks,
    ]
    for name, rows, delta_minimum, delta_maximum in banks:
        delta = np.arange(
            delta_minimum, delta_maximum+1, dtype=np.int64
        )
        require_range(f"{name} delta", delta, 18)
        for index, (c0, c1, c2) in enumerate(rows):
            require_range(f"{name} C0 row {index}", [c0], 29)
            require_range(f"{name} C1 row {index}", [c1], 20)
            require_range(f"{name} C2 row {index}", [c2], 9, signed=False)
            inner_product = delta*c2
            inner_correction = (inner_product+(1 << 15)) >> 15
            inner = c1+inner_correction
            outer_product = delta*inner
            outer_correction = (outer_product+(1 << 14)) >> 15
            polynomial = c0+outer_correction
            require_range(
                f"{name} inner product row {index}", inner_product, 28
            )
            require_range(
                f"{name} inner correction row {index}", inner_correction, 14
            )
            require_range(f"{name} inner row {index}", inner, 20)
            require_range(
                f"{name} outer product row {index}", outer_product, 37
            )
            require_range(
                f"{name} outer correction row {index}", outer_correction, 22
            )
            require_range(f"{name} polynomial row {index}", polynomial, 29)


def generate_coefficient_block() -> str:
    elementary_gen = load_elementary_generator()
    elementary_gen.DELTA_FRACTION_BITS = 24
    exp_rows = []
    for index in range(64):
        scale = 2.0 ** (index / 64.0)
        row = elementary_gen.tune_row(
            lambda delta, scale=scale: scale * math.exp(delta),
            0.0,
            math.log(2.0) / 128.0,
            27,
            17,
            9,
        )
        # Q27からQ24への最終丸めbiasをC0へ織り込む。
        # 6区間は隣接table境界の単調性を保つため、さらに上げる。
        c0_bias = EXP_C0_BIAS_BY_INDEX.get(
            index, 7 if index in EXP_C0_BIAS_7_INDICES else 6
        )
        exp_rows.append((row[0] + c0_bias, row[1], row[2], row[3]))

    elementary_text = ELEMENTARY_RTL.read_text()
    validate_shared_datapath(exp_rows, elementary_text)
    c1_epsilon2_mask, c2_epsilon1_mask = reconstruction_masks(exp_rows)

    # expはC0だけをtableに持ち、C1/C2はC0の上位bitと64-bit maskから
    # 正確に再構成する。generator側でも元の係数との一致を検査する。
    lines = elementary_gen.compressed_array(
        "exp_c0_q27", 29, exp_rows, 0
    )
    lines.extend([
        "",
        "    // expのC1/C2はC0の上位と小さい補正から正確に再構成する。",
        "    // 各maskのbit jは、table index jで補正を1段増やすことを表す。",
        (
            "    localparam [63:0] exp_c1_epsilon2_mask = "
            f"64'h{c1_epsilon2_mask:016x};"
        ),
        (
            "    localparam [63:0] exp_c2_epsilon1_mask = "
            f"64'h{c2_epsilon1_mask:016x};"
        ),
    ])

    root_prefix_names = (
        "reciprocal_c0_q25",
        "reciprocal_c1_q17",
        "rsqrt_base_c0_q25",
        "rsqrt_base_c1_q17",
        "rsqrt_scaled_c0_q25",
        "rsqrt_scaled_c1_q17",
    )
    root_suffix_names = (
        "reciprocal_c2_q8",
        "rsqrt_base_c2_q8",
        "rsqrt_scaled_c2_q8",
    )
    root_blocks = {
        name: array_block(elementary_text, name) for name in root_prefix_names
    }
    root_blocks.update({
        name: suffix_array_block(elementary_text, name)
        for name in root_suffix_names
    })
    root_order = (
        "reciprocal_c0_q25",
        "reciprocal_c1_q17",
        "reciprocal_c2_q8",
        "rsqrt_base_c0_q25",
        "rsqrt_base_c1_q17",
        "rsqrt_base_c2_q8",
        "rsqrt_scaled_c0_q25",
        "rsqrt_scaled_c1_q17",
        "rsqrt_scaled_c2_q8",
    )
    return "\n".join(lines) + "\n\n" + "\n\n".join(
        root_blocks[name] for name in root_order
    )


def replace_scalar(text: str, name: str, width: int, value: int) -> str:
    pattern = re.compile(
        rf"(    localparam logic \[{width - 1}:0\] {name} = )"
        rf"{width}'h[0-9a-fA-F]+;"
    )
    replaced, count = pattern.subn(rf"\g<1>{width}'h{value:x};", text)
    if count != 1:
        raise SystemExit(f"{name}を一意に抽出できません: {TARGET}")
    return replaced


def generate_text(text: str) -> str:
    match = COEFFICIENT_BLOCK.search(text)
    if match is None:
        raise SystemExit(f"係数tableを抽出できません: {TARGET}")
    generated = text[:match.start()] + generate_coefficient_block() + text[match.end():]
    inv_ln2_64_q8 = math.floor((64.0 / math.log(2.0)) * (1 << 8) + 0.5)
    ln2_by_64_q27 = math.floor((math.log(2.0) / 64.0) * (1 << 27) + 0.5)
    generated = replace_scalar(
        generated, "INV_LN2_64_Q8", 15, inv_ln2_64_q8
    )
    return replace_scalar(
        generated, "LN2_BY_64_Q27", 21, ln2_by_64_q27
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    text = TARGET.read_text()
    generated = generate_text(text)

    if args.check:
        if text != generated:
            raise SystemExit(f"再生成した定数と係数tableが一致しません: {TARGET}")
        print(f"PASS: {TARGET} の定数・係数tableとRTLが一致しました")
        return

    TARGET.write_text(generated)
    print(TARGET)


if __name__ == "__main__":
    main()
