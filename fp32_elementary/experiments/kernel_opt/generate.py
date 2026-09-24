#!/usr/bin/env python3
# Copyright 2026 Ryota Shioya and Toru Koizumi
# SPDX-License-Identifier: Apache-2.0
"""基準RTLから残差幅削減と積和統合を独立に生成する。"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

import numpy as np

UNIT = Path(__file__).resolve().parents[2]
BASE_COMMIT = 'bc9b4f22271a1eb93012c62141401e7581e05893'
BASE_SHA = '0b137ec34e8e92263d76191b13c72c3368d67d8c9e9c29b7730e897f2bad1832'
VARIANTS = ('baseline', 'delta18', 'inner', 'outer', 'both',
            'delta18-inner', 'delta18-outer', 'delta18-both')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def baseline_bytes():
    # 採用トップが更新されても、比較元を公開repository内の固定commitから復元する。
    raw = subprocess.run(
        ['git', '-C', str(UNIT.parent), 'show',
         f'{BASE_COMMIT}:fp32_elementary/fp32_elementary.sv'],
        check=True, stdout=subprocess.PIPE).stdout
    assert sha(raw) == BASE_SHA, '基準RTLのhashが一致しない'
    return raw


def table(text, name):
    match = re.search(rf"localparam \[(\d+):0\] {name}_suffix \[0:(\d+)\] = '\{{(.*?)\n    \}};", text, re.S)
    width = int(match[1])+1
    values = np.array([int(v) for v in re.findall(rf"{width}'d(\d+)", match[3])], dtype=np.int64)
    assert len(values) == int(match[2])+1
    prefix = re.search(rf"localparam \[(\d+):0\] {name}_prefix = \d+'b([01]+);", text)
    full_width = width+int(prefix[1])+1
    values |= int(prefix[2], 2) << width
    return np.where(values >> (full_width-1), values-(1 << full_width), values)


def retune(text):
    spec = importlib.util.spec_from_file_location('constants', UNIT/'tools/gen_constants.py')
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    c0s, c1s, c2s = (table(text, f'exp2_c{i}_q{q}') for i, q in enumerate((27, 17, 9)))
    domains = []
    for index, (c0, c1, c2) in enumerate(zip(c0s, c1s, c2s)):
        delta, lower, upper = generator.exp2_polynomial_bounds(index)
        delta = np.minimum(delta, 131071)
        inner = 2*c1+((delta*c2+16384) >> 15)
        correction = (delta*inner+16384) >> 15
        lo, hi = int(np.max(lower-correction)), int(np.min(upper-correction))
        domain = []
        for candidate in range(lo, hi+1):
            output = generator.pack_exp2_reduced_q27(candidate+correction)
            if np.any(np.diff(output) < 0):
                continue
            domain.append((candidate, int(output[0]), int(output[-1]), abs(candidate-int(c0))))
        assert domain, (index, lo, hi)
        domains.append(domain)
    best = None
    for first in domains[0]:
        states = [(first[3], [first])]
        for domain in domains[1:]:
            next_states = []
            for candidate in domain:
                compatible = [(cost, path) for cost, path in states if path[-1][2] <= candidate[1]]
                if compatible:
                    cost, path = min(compatible, key=lambda state: state[0])
                    next_states.append((cost+candidate[3], path+[candidate]))
            states = next_states
        for cost, path in states:
            if path[-1][2] <= first[1]+(1 << 23) and (best is None or cost < best[0]):
                best = cost, path
    assert best is not None
    selected = [row[0] for row in best[1]]
    changes = [dict(row=i, before=int(old), after=new)
               for i, (old, new) in enumerate(zip(c0s, selected)) if old != new]
    return selected, changes


def section(text, start, end, replacement):
    assert text.count(start) == text.count(end) == 1
    begin, finish = text.index(start), text.index(end)
    assert begin < finish
    return text[:begin]+replacement+text[finish:]


def candidate(baseline, name, c0):
    text = baseline
    if 'delta18' in name:
        # prefixは保持し、suffixだけを生成値で置き換える。
        match = re.search(r"localparam \[26:0\] exp2_c0_q27_suffix \[0:63\] = '\{(.*?)\n    \};", text, re.S)
        assert match is not None
        values = iter(c0)
        body = re.sub(r"27'd\d+", lambda _: f"27'd{next(values) & ((1 << 27)-1)}", match[1])
        text = text[:match.start(1)]+body+text[match.end(1):]
        text = section(text, '    wire signed [18:0] polynomial_delta_q24',
                       '    // 各bankで共通する上位bit', '''    // Q24の精度は維持し、exp2の正端点だけsigned 18-bit最大値へ制限する。
    wire signed [17:0] exp2_delta_clamped_q24 = exp2_delta_q24[18:17] == 2'b01
        ? 18'sd131071 : exp2_delta_q24[17:0];
    wire signed [17:0] polynomial_delta_q24 = select_recip | select_rsqrt
        ? {mantissa_delta_m7_q23, 1'b0}
        : select_sqrt | select_log2 ? {mantissa_delta_m6_q23[16:0], 1'b0}
        : select_exp2 ? exp2_delta_clamped_q24
        : ENABLE_SINCOS ? {sine_delta_q23, 1'b0} : 18'sd0;

''')
    if 'inner' in name or 'both' in name:
        text = section(text, '    wire signed [31:0] inner_product_q33',
                       '    wire signed [39:0] outer_product_q42', '''    // C1をQ33へ揃えて加え、従来と同じ位置でQ18へ丸める。
    wire signed [35:0] inner_accumulator_q33 =
        $signed({coefficient_c1_q17, 16'b0})
        + polynomial_delta_q24*coefficient_c2_q9 + 36'sd16384;
    wire signed [20:0] inner_q18 = inner_accumulator_q33[35:15];
''')
    if 'outer' in name or 'both' in name:
        text = section(text, '    wire signed [39:0] outer_product_q42',
                       '    // 数学的に厳密な格子点', '''    // 非exp2のC0はQ27整数で4の倍数。Q25丸め後も同じ値になる。
    wire signed [43:0] outer_accumulator_q42 =
        $signed({coefficient_c0_q27, 15'b0})
        + polynomial_delta_q24*inner_q18
        + (select_exp2 ? 44'sd16384 : 44'sd65536);
    wire signed [28:0] polynomial_q27 = select_exp2
        ? outer_accumulator_q42[43:15] : {outer_accumulator_q42[43:17], 2'b0};

''')
    return text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    raw = baseline_bytes()
    assert sha(raw) == BASE_SHA, '基準RTLが変更されている'
    baseline = raw.decode()
    c0, changes = retune(baseline)
    products = {f'{name}.sv': candidate(baseline, name, c0).encode() for name in VARIANTS}
    manifest = dict(baseline_sha256=BASE_SHA, c0_changes=changes,
                    sources_sha256={name: sha(data) for name, data in products.items()},
                    generator_sha256=sha(Path(__file__).read_bytes()),
                    constants_generator_sha256=sha((UNIT/'tools/gen_constants.py').read_bytes()))
    products['manifest.json'] = (json.dumps(manifest, indent=2)+'\n').encode()
    if not args.check:
        args.output.mkdir(parents=True, exist_ok=True)
    for name, data in products.items():
        path = args.output/name
        if args.check or path.exists():
            assert path.read_bytes() == data, path
        else:
            path.write_bytes(data)
    print(json.dumps(dict(status='PASS', variants=len(VARIANTS), c0_changes=changes, check=args.check)))


if __name__ == '__main__':
    main()
