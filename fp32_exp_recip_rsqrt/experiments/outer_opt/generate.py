#!/usr/bin/env python3
# Copyright 2026 Ryota Shioya and Toru Koizumi
# SPDX-License-Identifier: Apache-2.0
"""公開係数と変更区間外を固定して第2積の候補・比較topを生成する。"""
import argparse
import hashlib
import json
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2]
BASE = PACKAGE / 'fp32_exp_recip_rsqrt.sv'
OUT = PACKAGE / 'build/outer-opt'
BASE_HASH = '8b6f2d158e6d41d0ea4e342d7d3ad8400c4cc7015607ec946d427688a722d426'
VARIANTS = ('baseline', 'centered', 'rounding', 'combined')
START = '    wire signed [37:0] outer_product_q42 ='
STOP = '    wire [24:0] exp_mant = polynomial_mant_q24;'

CENTERED = '''    // expだけQ18の1を分離する。減算は下位19 bitのbit 18反転で表せる。
    wire signed [18:0] outer_inner_q18 = $signed({
        inner_q18[18] ^ select_exp, inner_q18[17:0]
    });
    wire signed [17:0] outer_linear_q24 = select_exp
        ? polynomial_delta_q24 : 18'sd0;
    // 線形項は固定shiftで戻し、積と同じ加算群へ渡す。
    wire signed [37:0] outer_product_q42 = polynomial_delta_q24*outer_inner_q18
        + $signed({{2{outer_linear_q24[17]}}, outer_linear_q24, 18'b0});
'''

ROUNDING = '''    // 中間丸めのguardを低位和へ移す。根系の最終増分は2になる場合もある。
    wire [3:0] pack_low_sum = {1'b0, coefficient_c0_q27[2:0]}
        + {1'b0, outer_product_q42[17:15]}
        + {3'b0, outer_product_q42[14]};
    wire pack_upper_odd = coefficient_c0_q27[3] ^ outer_product_q42[18]
        ^ pack_low_sum[3];
    wire root_round_increment = pack_low_sum[2]
        & (pack_low_sum[1] | pack_low_sum[0] | pack_upper_odd);
    wire [1:0] pack_increment = {1'b0, pack_low_sum[3]}
        + {1'b0, (~select_exp & root_round_increment)};
    // 上位25 bitのmodulo和。補正は算術shiftしたsigned値として加える。
    wire [24:0] polynomial_mant_q24 = coefficient_c0_q27[27:3]
        + {{6{outer_product_q42[36]}}, outer_product_q42[36:18]}
        + {23'b0, pack_increment};
'''


def replace_once(text, before, after):
    assert text.count(before) == 1
    return text.replace(before, after, 1)


def generate():
    source = BASE.read_text()
    assert hashlib.sha256(BASE.read_bytes()).hexdigest() == BASE_HASH
    first = source.index(START)
    last = source.index(STOP)
    original = source[first:last]
    products = original[:original.index('    wire signed [38:0] outer_product_biased_q42')]
    tails = original[len(products):]
    result = {}
    for variant in VARIANTS:
        block = (CENTERED if variant in ('centered', 'combined') else products)
        block += (ROUNDING if variant in ('rounding', 'combined') else tails)
        rtl = source[:first]+block+source[last:]
        assert rtl[:first] == source[:first]
        assert rtl[rtl.index(STOP):] == source[last:]
        result[f'{variant}/fp32_exp_recip_rsqrt.sv'] = rtl

    tables = source[source.index('    localparam [1:0] exp_c0_q27_prefix'):source.index('    wire select_exp =')]
    kernel = []
    full = []
    for variant in VARIANTS:
        rtl = result[f'{variant}/fp32_exp_recip_rsqrt.sv']
        name = variant.title()
        full.append(replace_once(rtl, 'module FP32ExpRecipRsqrt', f'module {name}Full'))
        body = rtl[rtl.index('    wire signed [28:0] exp_c0_q27_value'):rtl.index(STOP)]
        kernel.append(f'''module {name}Kernel (
    input wire [1:0] bank, input wire [6:0] index,
    input wire signed [17:0] polynomial_delta_q24, output wire [24:0] result
);
{tables}
    wire select_exp = bank == 2'd0;
    wire select_recip = bank == 2'd1;
    wire exponent_parity = bank == 2'd3;
    wire [5:0] exp_table_index = index[5:0];
    wire [6:0] mantissa_index_m7 = index;
{body}
    assign result = polynomial_mant_q24;
endmodule
''')
    ports = ', '.join(VARIANTS)
    kernel.append(f'''module KernelCheck(input wire [1:0] bank, input wire [6:0] index,
    input wire [17:0] delta, output wire [24:0] {ports});
''')
    full.append(f'''module FullCheck(input wire [31:0] x, input wire [2:0] op,
    output wire [31:0] {ports});
''')
    for variant in VARIANTS:
        kernel.append(f'{variant.title()}Kernel k_{variant}(bank, index, delta, {variant});\n')
        full.append(f'{variant.title()}Full f_{variant}(x, op, {variant});\n')
    kernel.append('endmodule\n')
    full.append('endmodule\n')
    result['kernel.sv'] = '\n'.join(kernel)
    result['full.sv'] = '\n'.join(full)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    generated = generate()
    for relative, text in generated.items():
        path = OUT / relative
        if args.check:
            assert path.read_text() == text, path
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
    manifest = dict(base_sha256=BASE_HASH, source_sha256={name: hashlib.sha256(text.encode()).hexdigest()
                                                       for name, text in generated.items()})
    encoded = json.dumps(manifest, indent=2)+'\n'
    if args.check:
        assert (OUT/'sources.json').read_text() == encoded
    else:
        (OUT/'sources.json').write_text(encoded)
    print('PASS: variants, constants and unchanged regions match the pinned baseline')


if __name__ == '__main__':
    main()
