#!/usr/bin/env python3
# Copyright 2026 Ryota Shioya and Toru Koizumi
# SPDX-License-Identifier: Apache-2.0
"""全根系仮数の実数誤差をlong doubleで診断する。合否の整数参照とは区別する。"""
import json
import numpy as np
from generate import OUT, BANKS, table

results=[]
offset=np.arange(65536,dtype=np.int64)
d=2*(offset-32768)
for variant in ('baseline','single-round','root-floor','c0-q24','c0-q24-single'):
    text=(OUT/variant/'fp32_exp_recip_rsqrt.sv').read_text()
    for bank,name in enumerate(BANKS):
        small=variant.startswith('c0-q24')
        a=table(text,f'{name}_c0_q{24 if small else 25}')
        if small: a=[v*2 for v in a]
        b=table(text,f'{name}_c1_q17'); c=table(text,f'{name}_c2_q8')
        stats=dict(variant=variant,bank=name,inputs=0,minimum_error_ulp=1e9,maximum_error_ulp=-1e9,
                   worst_absolute_error_ulp=0,worst_fraction=0)
        for row in range(128):
            f=(row<<16)+offset
            m=1+f.astype(np.longdouble)/(1<<23)
            ideal=(1<<24)/(m if bank==0 else np.sqrt(m*(2 if bank==2 else 1)))
            p=d*(2*b[row]+((d*(2*c[row])+32768)>>15))
            if variant in ('single-round','c0-q24-single'):
                y=((a[row]<<17)+p+131072)>>18
            else:
                value=4*a[row]+((p+(0 if variant=='root-floor' else 16384))>>15)
                high=value>>3; low=value&7
                y=high+((low>4)|((low==4)&((high&1)!=0)))
            if bank!=2 and row==0: y[0]=1<<24
            error=y.astype(np.longdouble)-ideal
            stats['inputs']+=len(error)
            stats['minimum_error_ulp']=min(stats['minimum_error_ulp'],float(error.min()))
            stats['maximum_error_ulp']=max(stats['maximum_error_ulp'],float(error.max()))
            worst=int(np.argmax(np.abs(error)))
            if abs(error[worst])>stats['worst_absolute_error_ulp']:
                stats['worst_absolute_error_ulp']=float(abs(error[worst]))
                stats['worst_fraction']=int(f[worst])
        results.append(stats)
print(json.dumps(dict(reference='long double diagnostic, not an interval proof',results=results),indent=2))
