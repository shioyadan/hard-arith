#!/usr/bin/env python3
# Copyright 2026 Ryota Shioya and Toru Koizumi
# SPDX-License-Identifier: Apache-2.0
"""公開版を固定し、数値探索入力と独立した最適化候補を生成する。"""
import argparse
import hashlib
import json
from pathlib import Path
import re

PACKAGE = Path(__file__).resolve().parents[2]
BASE = PACKAGE / 'fp32_exp_recip_rsqrt.sv'
OUT = PACKAGE / 'build/numeric-opt'
BASE_HASH = '8b6f2d158e6d41d0ea4e342d7d3ad8400c4cc7015607ec946d427688a722d426'
BANKS = ('reciprocal', 'rsqrt_base', 'rsqrt_scaled')


def table(text, name):
    m = re.search(rf"localparam \[(\d+):0\] {name}_suffix \[0:(\d+)\] = '\{{(.*?)\n    \}};", text, re.S)
    assert m, name
    sw = int(m[1])+1
    values = [int(v) for v in re.findall(rf"{sw}'d(\d+)", m[3])]
    assert len(values) == int(m[2])+1
    p = re.search(rf"localparam \[(\d+):0\] {name}_prefix = \d+'b([01]+);", text)
    if p:
        width = int(p[1])+1+sw
        values = [(int(p[2], 2) << sw)|v for v in values]
        values = [v-(1 << width) if v >> (width-1) else v for v in values]
    return values


def replace(text, before, after):
    assert text.count(before) == 1, before
    return text.replace(before, after, 1)


def retable(text, name, values, drop=0):
    pattern = rf"localparam \[(\d+):0\] {name}_suffix \[0:127\] = '\{{(.*?)\n    \}};"
    m = re.search(pattern, text, re.S)
    assert m and len(values) == 128
    width = int(m[1])+1
    p = re.search(rf"localparam \[(\d+):0\] {name}_prefix = \d+'b([01]+);", text)
    if p:
        total = width+int(p[1])+1
        assert all(((v & ((1<<total)-1))>>width) == int(p[2],2) for v in values)
    assert all(v % (1<<drop) == 0 for v in values)
    values = [(v & ((1<<width)-1))>>drop for v in values]
    width -= drop
    body = f"localparam [{width-1}:0] {name}_suffix [0:127] = '{{\n"
    for start in range(0,128,4):
        body += '        '+', '.join(f"{width}'d{v}" for v in values[start:start+4])
        body += ',\n' if start < 124 else '\n'
    body += '    };'
    return text[:m.start()]+body+text[m.end():]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--coefficients', type=Path)
    args = parser.parse_args()
    source = BASE.read_text()
    assert hashlib.sha256(source.encode()).hexdigest() == BASE_HASH
    generated = {'baseline/fp32_exp_recip_rsqrt.sv': source}
    signed = replace(source, '''    wire signed [14:0] exp_n = x_sign
        ? -$signed({1'b0, exp_n_abs}) : $signed({1'b0, exp_n_abs});''', '''    // 絶対値丸めと符号反転を統合する。正のn_absは残差生成のため残す。
    wire [14:0] exp_signed_base = {1'b0, exp_index_window[14:1]} ^ {15{x_sign}};
    wire signed [14:0] exp_n = $signed(exp_signed_base)
        + $signed({14'b0, (exp_index_window[0] ^ x_sign)});''')
    generated['signed-round/fp32_exp_recip_rsqrt.sv'] = signed
    start = source.index('    wire signed [37:0] outer_product_q42 =')
    stop = source.index('    wire [24:0] exp_mant = polynomial_mant_q24;')
    single = '''    // 根系は中間丸めをせずC0も積和へ入れ、最後に最近接（tieは正側）へ丸める。
    // expは既存のC0内biasと第2積のbiasを保持し、元の出力に一致させる。
    wire signed [43:0] polynomial_q42 = polynomial_delta_q24*inner_q18
        + $signed({coefficient_c0_q27, 15'b0})
        + (select_exp ? 44'sd16384 : 44'sd131072);
    wire [24:0] polynomial_mant_q24 = polynomial_q42[42:18];
'''
    generated['single-round/fp32_exp_recip_rsqrt.sv'] = source[:start]+single+source[stop:]
    generated['root-floor/fp32_exp_recip_rsqrt.sv'] = replace(source,
        "$signed({outer_product_q42[37], outer_product_q42})+39'sd16384;",
        "$signed({outer_product_q42[37], outer_product_q42})\n"
        "        + (select_exp ? 39'sd16384 : 39'sd0);")
    header = '// 自動生成。C0/C1/C2はQ25/Q17/Q8。\nstatic constexpr Coeff baseline[3][128] = {\n'
    for bank in BANKS:
        rows = zip(*(table(source, f'{bank}_c{k}_q{q}') for k, q in enumerate((25, 17, 8))))
        header += '{\n'+''.join(f'{{{a},{b},{c}}},\n' for a, b, c in rows)+'},\n'
    generated['coefficients.hpp'] = header+'};\n'
    if args.coefficients:
        log = args.coefficients.read_text()
        assert len(re.findall(r'^SEARCH .* rows=128/128 failed= boundary_path=1$', log, re.M)) == 6
        for mode in (0, 1):
            rtl = generated['single-round/fp32_exp_recip_rsqrt.sv'] if mode else source
            for bank, name in enumerate(BANKS):
                rows = re.findall(rf'^COEFF {bank} {mode} (\d+) 1 (-?\d+) (-?\d+) (-?\d+)$', log, re.M)
                assert [int(r[0]) for r in rows] == list(range(128))
                for k,q in enumerate((25,17,8)):
                    values = [int(r[k+1]) for r in rows]
                    rtl = retable(rtl, f'{name}_c{k}_q{q}', values, drop=int(k==0))
                rtl = replace(rtl, f'{name}_c0_q25_suffix[mantissa_index_m7], 2\'b0',
                              f'{name}_c0_q25_suffix[mantissa_index_m7], 3\'b0')
                rtl = rtl.replace(f'{name}_c0_q25', f'{name}_c0_q24')
            generated[('c0-q24-single' if mode else 'c0-q24')+'/fp32_exp_recip_rsqrt.sv'] = rtl
    for name, text in generated.items():
        path = OUT/name
        if args.check:
            assert path.read_text() == text, path
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
    manifest = dict(base_sha256=BASE_HASH,
                    source_sha256={n: hashlib.sha256(t.encode()).hexdigest() for n, t in generated.items()})
    if args.coefficients:
        manifest['coefficient_search_sha256'] = hashlib.sha256(args.coefficients.read_bytes()).hexdigest()
    encoded = json.dumps(manifest, indent=2)+'\n'
    if args.check:
        assert (OUT/'sources.json').read_text() == encoded
    else:
        (OUT/'sources.json').write_text(encoded)
    print('PASS: numeric-opt source generation and baseline binding')


if __name__ == '__main__':
    main()
