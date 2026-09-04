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


ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = Path(__file__).resolve().parents[1]
TARGET = PACKAGE_DIR / "fp32_exp_recip_rsqrt.sv"
ELEMENTARY_RTL = ROOT / "fp32_elementary/fp32_elementary.sv"
ELEMENTARY_GENERATOR = ROOT / "fp32_elementary/tools/gen_constants.py"
EXP_C0_BIAS_7_INDICES = {21, 41, 50}
EXP_C0_BIAS_BY_INDEX = {10: 9, 55: 9, 58: 10}

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

    lines: list[str] = []
    elementary_gen.append_tables(lines, "exp", exp_rows, 27, 17, 9)

    elementary_text = ELEMENTARY_RTL.read_text()
    root_names = (
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
        array_block(elementary_text, name) for name in root_names
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
