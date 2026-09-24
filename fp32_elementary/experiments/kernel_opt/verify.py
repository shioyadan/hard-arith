#!/usr/bin/env python3
# Copyright 2026 Ryota Shioya and Toru Koizumi
# SPDX-License-Identifier: Apache-2.0
"""候補と基準を同じ入力で走査し、数値仕様とbit一致を分けて確認する。"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import subprocess

from generate import BASE_SHA, UNIT, VARIANTS


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(args, log):
    with log.open('x') as stream:
        result = subprocess.run(args, cwd=UNIT, stdout=stream, stderr=subprocess.STDOUT)
    text = log.read_text()
    assert result.returncode == 0, log
    assert not re.search(r'%Warning|%Error|Fatal:|FAIL:|Error-\[|\$fatal', text), log
    return text


def verify(sources, output, name, threads):
    root = output/name
    root.mkdir(parents=True, exist_ok=False)
    rtl = sources/f'{name}.sv'
    manifest = json.loads((sources/'manifest.json').read_text())
    assert digest(rtl) == manifest['sources_sha256'][rtl.name]
    assert digest(sources/'baseline.sv') == BASE_SHA
    inputs = [rtl, sources/'baseline.sv', UNIT/'Makefile', UNIT/'test/exhaustive.cpp',
              UNIT/'test/reference.c', UNIT/'test/tb_fp32_elementary.sv', Path(__file__)]
    frozen = {str(path): digest(path) for path in inputs}
    command(['make', 'test', f'RTL={rtl}', f'BUILD_DIR={root / "quick"}'], root/'quick.log')
    baseline = (sources/'baseline.sv').read_text().replace('module FP32Elementary #(', 'module Baseline #(')
    changed = rtl.read_text().replace('module FP32Elementary #(', 'module Candidate #(')
    pair = root/'pair.sv'
    pair.write_text(baseline+'\n'+changed+'''
// 数値testの各入力で、同値変形候補の出力も基準と照合する。
module FP32ElementaryPair(
    input wire [31:0] x, input wire [6:0] op,
    output wire [31:0] result, output wire [31:0] baseline_result,
    output wire may_differ
);
    Baseline baseline(.x(x), .op(op), .result(baseline_result));
    Candidate candidate(.x(x), .op(op), .result(result));
    assign may_differ = '''+("op == 7'd1" if 'delta18' in name else "1'b0")+''';
endmodule
''')
    cpp = root/'pair.cpp'
    source = (UNIT/'test/exhaustive.cpp').read_text().replace('VFP32Elementary', 'VFP32ElementaryPair')
    old = '    dut.eval();\n    return dut.result;'
    assert source.count(old) == 1
    source = source.replace(old, '''    dut.eval();
    if (!dut.may_differ && dut.result != dut.baseline_result) {
        std::cerr << "FAIL: equivalence x=" << std::hex << input << " op=" << op
                  << " candidate=" << dut.result << " baseline=" << dut.baseline_result << std::endl;
        std::abort();
    }
    return dut.result;''')
    cpp.write_text(source)
    command(['verilator', '--cc', '--exe', '--build', '--build-jobs', '4', '-O3',
             '--Wall', '--Wno-DECLFILENAME', '--Wno-UNUSEDSIGNAL',
             '--top-module', 'FP32ElementaryPair', '--Mdir', str(root/'pair'), str(pair), str(cpp),
             str(UNIT/'test/reference.c'), '-CFLAGS', '-O3 -march=native -std=gnu++20 -fopenmp',
             '-LDFLAGS', '-fopenmp -lquadmath -lm'], root/'build.log')
    binary = root/'pair/VFP32ElementaryPair'
    for mode, expected in [('reduced-only', 13), ('exp2-full-only', 1)]:
        log = command([str(binary), f'--{mode}', f'--threads={threads}'], root/f'{mode}.log')
        assert log.count('\npass=1\n') == 1
        assert len(re.findall(r'^function=', log, re.M)) == expected
        for field in ('violations', 'monotonic_violations', 'first_failure_present'):
            assert re.findall(rf'^{field}=(\d+)$', log, re.M) == ['0']*expected, field
        if mode == 'exp2-full-only':
            assert 'exp2_special_mismatches=0' in log
    for path, sha in frozen.items():
        assert digest(Path(path)) == sha
    record = dict(status='PASS', variant=name, threads=threads, inputs_sha256=frozen,
                  evidence_sha256={p.name: digest(p) for p in root.glob('*.log')},
                  generated_sha256={p.name: digest(p) for p in (pair, cpp)})
    (root/'verification.json').write_text(json.dumps(record, indent=2)+'\n')
    print('PASS', name, flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--variants', nargs='+', choices=VARIANTS, default=list(VARIANTS))
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--threads', type=int, default=8)
    args = parser.parse_args()
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        tasks = [executor.submit(verify, args.sources.resolve(), args.output.resolve(), name, args.threads)
                 for name in args.variants]
        for task in tasks:
            task.result()


if __name__ == '__main__':
    main()
