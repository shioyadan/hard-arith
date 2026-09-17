#!/usr/bin/env python3
# Copyright 2026 Ryota Shioya and Toru Koizumi
# SPDX-License-Identifier: Apache-2.0
"""固定した公開版から一回丸めの後続候補を生成・照合する。"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
spec=importlib.util.spec_from_file_location('numeric_generate',Path(__file__).resolve().parents[1]/'numeric_opt/generate.py')
numeric=importlib.util.module_from_spec(spec)
spec.loader.exec_module(numeric)
BASE,BASE_HASH,BANKS=numeric.BASE,numeric.BASE_HASH,numeric.BANKS
table,retable,replace=numeric.table,numeric.retable,numeric.replace

OUT = BASE.parent/'build/refine-opt'
VARIANTS = ('baseline', 'single-round', 'centered-single', 'bias-single', 'minimax-q24', 'mixed-q24')


def generate(search=None):
    source = BASE.read_text()
    assert hashlib.sha256(source.encode()).hexdigest() == BASE_HASH
    start = source.index('    wire signed [37:0] outer_product_q42 =')
    stop = source.index('    wire [24:0] exp_mant = polynomial_mant_q24;')
    block = '''    // 根系は中間丸めをせずC0も積和へ入れ、最後に最近接（tieは正側）へ丸める。
    // expは既存のC0内biasと第2積のbiasを保持し、元の出力に一致させる。
    wire signed [43:0] polynomial_q42 = polynomial_delta_q24*inner_q18
        + $signed({coefficient_c0_q27, 15'b0})
        + (select_exp ? 44'sd16384 : 44'sd131072);
    wire [24:0] polynomial_mant_q24 = polynomial_q42[42:18];
'''
    single = source[:start]+block+source[stop:]
    centered = '''    // expだけQ18の1を分離し、19 bitの乗算と同じ加算群へ線形項を戻す。
    wire signed [18:0] outer_inner_q18 = $signed({
        inner_q18[18] ^ select_exp, inner_q18[17:0]
    });
    wire signed [17:0] outer_linear_q24 = select_exp
        ? polynomial_delta_q24 : 18'sd0;
    wire signed [43:0] polynomial_q42 = polynomial_delta_q24*outer_inner_q18
        + $signed({{8{outer_linear_q24[17]}}, outer_linear_q24, 18'b0})
        + $signed({coefficient_c0_q27, 15'b0})
        + (select_exp ? 44'sd16384 : 44'sd131072);
    wire [24:0] polynomial_mant_q24 = polynomial_q42[42:18];
'''
    bias = replace(single, "44'sd16384 : 44'sd131072", "44'sd16384 : 44'sd0")
    bias = replace(bias,
        '    // 根系は中間丸めをせずC0も積和へ入れ、最後に最近接（tieは正側）へ丸める。',
        '    // 根系の最近接biasはQ25 C0へ1を加えて格納してある。')
    for bank in BANKS:
        name = f'{bank}_c0_q25'
        bias = retable(bias, name, [v+1 for v in table(source, name)])
    generated = dict(baseline=source, **{'single-round':single,
                     'centered-single':source[:start]+centered+source[stop:], 'bias-single':bias})
    if search:
        log = search.read_text()
        assert len(re.findall(r'^SEARCH .* rows=128/128 boundary_path=1$', log, re.M)) == 6
        for mode, variant in enumerate(('minimax-q24','mixed-q24')):
            rtl = single
            for bank, name in enumerate(BANKS):
                rows = re.findall(rf'^COEFF {bank} {mode} (\d+) (-?\d+) (-?\d+) (-?\d+)$', log, re.M)
                assert [int(r[0]) for r in rows] == list(range(128))
                for k,q in enumerate((25,17,8)):
                    rtl = retable(rtl, f'{name}_c{k}_q{q}', [int(r[k+1]) for r in rows],
                                  drop=int(mode==0 and k==0))
                if mode==0:
                    rtl = replace(rtl, f"{name}_c0_q25_suffix[mantissa_index_m7], 2'b0",
                                  f"{name}_c0_q25_suffix[mantissa_index_m7], 3'b0")
                    rtl = rtl.replace(f'{name}_c0_q25',f'{name}_c0_q24')
            generated[variant] = rtl
    result = {v+'/fp32_exp_recip_rsqrt.sv':text for v,text in generated.items()}
    header = '// 自動生成。C0/C1/C2はQ25/Q17/Q8。\nstatic constexpr Coeff baseline[3][128] = {\n'
    for bank in BANKS:
        rows = zip(*(table(source,f'{bank}_c{k}_q{q}') for k,q in enumerate((25,17,8))))
        header += '{\n'+''.join(f'{{{a},{b},{c}}},\n' for a,b,c in rows)+'},\n'
    result['coefficients.hpp'] = header+'};\n'
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--search',type=Path)
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    result=generate(args.search)
    manifest=dict(base_sha256=BASE_HASH,source_sha256={p:hashlib.sha256(t.encode()).hexdigest() for p,t in result.items()})
    if args.search: manifest['search_sha256']=hashlib.sha256(args.search.read_bytes()).hexdigest()
    result['sources.json']=json.dumps(manifest,indent=2)+'\n'
    for name,text in result.items():
        path=OUT/name
        if args.check: assert path.read_text()==text,path
        else:
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(text)
    print('PASS: refine-opt generation and fixed public source')


if __name__=='__main__': main()
