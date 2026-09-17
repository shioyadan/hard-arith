#!/usr/bin/env python3
# Copyright 2026 Ryota Shioya and Toru Koizumi
# SPDX-License-Identifier: Apache-2.0
"""固定した候補RTLから全入力比較topと根系係数を生成する。"""
import hashlib
import json
from generate import OUT, BANKS, table

variants = ('baseline','signed-round','single-round','root-floor','c0-q24','c0-q24-single')
manifest=json.loads((OUT/'sources.json').read_text())
rtl=[]
header='// 自動生成。根系係数の整数形式はQ25/Q17/Q8へ統一。\nstatic constexpr Coeff coefficients[6][3][128] = {\n'
for i,variant in enumerate(variants):
    name=f'{variant}/fp32_exp_recip_rsqrt.sv'
    text=(OUT/name).read_text()
    assert hashlib.sha256(text.encode()).hexdigest()==manifest['source_sha256'][name]
    rtl.append(text.replace('module FP32ExpRecipRsqrt',f'module Variant{i}',1))
    header+='{\n'
    for bank in BANKS:
        small=variant.startswith('c0-q24')
        c0=table(text,f'{bank}_c0_q{24 if small else 25}')
        if small: c0=[v*2 for v in c0]
        rows=zip(c0,table(text,f'{bank}_c1_q17'),table(text,f'{bank}_c2_q8'))
        header+='{\n'+''.join(f'{{{a},{b},{c}}},\n' for a,b,c in rows)+'},\n'
    header+='},\n'
header+='};\n'
rtl.append('module Verify(input wire [31:0] x, input wire [2:0] op, output wire [31:0] '+', '.join(f'v{i}' for i in range(6))+');\n')
for i in range(6): rtl.append(f'Variant{i} u{i}(x,op,v{i});\n')
rtl.append('endmodule\n')
(OUT/'verify.sv').write_text('\n'.join(rtl))
(OUT/'verify-coefficients.hpp').write_text(header)
print('PASS: verification top and model coefficients bind to all six source hashes')
