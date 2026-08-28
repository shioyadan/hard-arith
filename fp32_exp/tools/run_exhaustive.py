#!/usr/bin/env python3
# Copyright 2026 Ryota Shioya and Toru Koizumi
# SPDX-License-Identifier: Apache-2.0

"""FP32 expの全数検査を分割実行し、精度と単調性を集計する。"""

import argparse
import concurrent.futures
import json
import os
import subprocess
import time
from pathlib import Path


TOTAL_INPUTS = 1 << 29  # 2符号×32指数×2^23仮数を検査する。
SUM_FIELDS = (
    "total", "reference_zero", "reference_infinity", "reference_finite",
    "actual_zero", "actual_infinity", "correct", "one_ulp", "over_one_ulp",
    "finite_correct", "finite_one_ulp", "finite_over_one_ulp",
    "faithful_valid", "faithful_alternative", "faithful_violation",
    "faithful_below", "faithful_above", "faithful_ambiguous",
    "monotonic_violation",
)


def run_chunk(binary: Path, start: int, end: int, output: Path) -> dict:
    """一つの連続ordinal範囲を別processで検査する。"""
    subprocess.run(
        [str(binary), str(start), str(end), str(output)],
        check=True,
    )
    result = json.loads(output.read_text())
    if result["start"] != start or result["end"] != end:
        raise RuntimeError(f"shard範囲が一致しません: {output}")
    return result


def hexadecimal(value: int) -> str:
    """binary32 bit patternを8桁hexへ整形する。"""
    return f"0x{value:08x}"


def aggregate(results: list[dict], wall_seconds: float) -> dict:
    """連続shardを検査し、加算可能な指標と境界単調性をまとめる。"""
    ordered = sorted(results, key=lambda item: item["start"])
    if not ordered or ordered[0]["start"] != 0 or ordered[-1]["end"] != TOTAL_INPUTS:
        raise RuntimeError("全検査範囲の先頭または終端が欠けています")
    for previous, current in zip(ordered, ordered[1:]):
        if previous["end"] != current["start"]:
            raise RuntimeError("shard間に重複または欠落があります")

    summary = {field: sum(item[field] for item in ordered) for field in SUM_FIELDS}
    summary["start"] = 0
    summary["end"] = TOTAL_INPUTS
    summary["chunks"] = len(ordered)
    summary["wall_seconds"] = wall_seconds
    summary["worker_seconds"] = sum(item["elapsed_seconds"] for item in ordered)
    summary["throughput_per_second"] = TOTAL_INPUTS / wall_seconds

    worst = max(ordered, key=lambda item: item["max_ulp"])
    summary["max_ulp"] = worst["max_ulp"]
    summary["worst_input"] = worst["worst_input"]
    summary["worst_actual"] = worst["worst_actual"]
    summary["worst_reference"] = worst["worst_reference"]
    worst_finite = max(ordered, key=lambda item: item["max_finite_ulp"])
    summary["max_finite_ulp"] = worst_finite["max_finite_ulp"]
    summary["worst_finite_input"] = worst_finite["worst_finite_input"]
    summary["worst_finite_actual"] = worst_finite["worst_finite_actual"]
    summary["worst_finite_reference"] = worst_finite["worst_finite_reference"]

    faithful_failures = [item for item in ordered if item["first_faithful_ordinal"] != (1 << 64) - 1]
    if faithful_failures:
        first = min(faithful_failures, key=lambda item: item["first_faithful_ordinal"])
        for field in (
            "first_faithful_ordinal", "first_faithful_input",
            "first_faithful_actual", "first_faithful_lower",
            "first_faithful_upper",
        ):
            summary[field] = first[field]

    boundary_violations = 0
    first_boundary = None
    for previous, current in zip(ordered, ordered[1:]):
        if current["first_actual"] < previous["last_actual"]:
            boundary_violations += 1
            if first_boundary is None:
                first_boundary = {
                    "previous_input": previous["last_input"],
                    "previous_actual": previous["last_actual"],
                    "input": current["first_input"],
                    "actual": current["first_actual"],
                }
    summary["boundary_monotonic_violation"] = boundary_violations
    summary["monotonic_violation"] += boundary_violations
    if first_boundary is not None:
        summary["first_boundary_monotonic"] = first_boundary
    return summary


def text_report(summary: dict, jobs: int) -> str:
    """確定値を人が確認しやすい日本語textへ整形する。"""
    finite = summary["reference_finite"]
    correct_rate = 100.0 * summary["finite_correct"] / finite
    faithful_rate = 100.0 * summary["faithful_valid"] / finite
    lines = [
        "FP32 expの並列全数検査",
        "",
        "条件",
        f"- RTL: FP32Exp（FTZ、ROUND_OUTPUT=1）",
        "- 入力: exponent fieldが102以上133以下の全binary32 bit pattern",
        f"- 全列挙数: {summary['total']:,}",
        f"- 並列数: {jobs}",
        f"- shard数: {summary['chunks']}",
        "- 参照値: binary128 expqから得たcorrectly-rounded binary32、subnormalはFTZ",
        "- faithful判定: 厳密値の直下または直上のbinary32に一致すること",
        "",
        "全列挙結果",
        f"- correct一致: {summary['correct']:,}",
        f"- 1 ULP差: {summary['one_ulp']:,}",
        f"- 1 ULP超過: {summary['over_one_ulp']:,}",
        f"- 最大ULP: {summary['max_ulp']}",
        f"- 参照出力0: {summary['reference_zero']:,}",
        f"- 参照出力+Inf: {summary['reference_infinity']:,}",
        "",
        "参照出力が0でもInfでもない範囲",
        f"- 対象入力数: {finite:,}",
        f"- correct一致: {summary['finite_correct']:,} ({correct_rate:.8f}%)",
        f"- 1 ULP差: {summary['finite_one_ulp']:,}",
        f"- 1 ULP超過: {summary['finite_over_one_ulp']:,}",
        f"- 最大ULP: {summary['max_finite_ulp']}",
        f"- faithful: {summary['faithful_valid']:,} ({faithful_rate:.8f}%)",
        f"- correctではないがfaithful: {summary['faithful_alternative']:,}",
        f"- faithful違反: {summary['faithful_violation']:,}",
        f"- 下側違反: {summary['faithful_below']:,}",
        f"- 上側違反: {summary['faithful_above']:,}",
        f"- binary128で上下を決めにくい入力: {summary['faithful_ambiguous']:,}",
        "",
        "単調性",
        f"- 違反: {summary['monotonic_violation']:,}",
        f"- shard境界の違反: {summary['boundary_monotonic_violation']:,}",
        "",
        "実行時間",
        f"- wall time: {summary['wall_seconds']:.3f} s",
        f"- 合計worker time: {summary['worker_seconds']:.3f} s",
        f"- throughput: {summary['throughput_per_second']:,.0f} inputs/s",
    ]
    if summary["max_finite_ulp"] != 0:
        lines.extend([
            "",
            "非0有限範囲の最大ULP例",
            f"- input: {hexadecimal(summary['worst_finite_input'])}",
            f"- actual: {hexadecimal(summary['worst_finite_actual'])}",
            f"- reference: {hexadecimal(summary['worst_finite_reference'])}",
        ])
    if summary["faithful_violation"] != 0:
        lines.extend([
            "",
            "最初のfaithful違反",
            f"- input: {hexadecimal(summary['first_faithful_input'])}",
            f"- actual: {hexadecimal(summary['first_faithful_actual'])}",
            f"- lower: {hexadecimal(summary['first_faithful_lower'])}",
            f"- upper: {hexadecimal(summary['first_faithful_upper'])}",
        ])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=min(16, os.cpu_count() or 1))
    parser.add_argument("--chunks", type=int, default=64)
    args = parser.parse_args()
    if args.jobs <= 0 or args.chunks <= 0 or args.jobs > args.chunks:
        raise SystemExit("jobsとchunksは 0 < jobs <= chunks を満たす必要があります")
    binary = args.binary.resolve()
    if not binary.is_file():
        raise SystemExit(f"実行fileがありません: {binary}")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    ranges = []
    for index in range(args.chunks):
        start = TOTAL_INPUTS * index // args.chunks
        end = TOTAL_INPUTS * (index + 1) // args.chunks
        ranges.append((index, start, end, args.output_dir / f"chunk-{index:04d}.json"))

    begin = time.monotonic()
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as executor:
        future_to_range = {
            executor.submit(run_chunk, binary, start, end, output):
            (index, start, end)
            for index, start, end, output in ranges
        }
        completed_inputs = 0
        for future in concurrent.futures.as_completed(future_to_range):
            index, start, end = future_to_range[future]
            results.append(future.result())
            completed_inputs += end - start
            print(
                f"完了 {len(results)}/{args.chunks}: shard={index} "
                f"inputs={completed_inputs:,}/{TOTAL_INPUTS:,}",
                flush=True,
            )
    wall_seconds = time.monotonic() - begin
    summary = aggregate(results, wall_seconds)
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    report = text_report(summary, args.jobs)
    (args.output_dir / "summary.txt").write_text(report)
    print(report, end="")


if __name__ == "__main__":
    main()
