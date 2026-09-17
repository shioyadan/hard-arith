// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0
// 整数参照を別実装のbinary128値と標本照合する。
#include <cassert>
#include <iostream>
#include <quadmath.h>
#include "model.hpp"

int main() {
    unsigned random=0x8de19731;
    for (int bank=0;bank<3;++bank) for (int i=0;i<20000;++i) {
        random^=random<<13;random^=random>>17;random^=random<<5;
        const unsigned f=i<128 ? (unsigned(i)<<16):(random&0x7fffff);
        const __float128 m=1+__float128(f)/(1<<23);
        const __float128 y=__float128(1<<24)/(bank==0 ? m:sqrtq(m*(bank==2 ? 2:1)));
        for (int bits:{0,precision}) {
            const __float128 scaled=ldexpq(y,bits), floored=floorq(scaled);
            const I q=I(floored);
            const I r=q+(scaled-floored>0.5Q || (scaled-floored==0.5Q && (q&1)));
            assert(reference(bank,f,bits)==r);
        }
    }
    std::cout<<"PASS: integer reference versus binary128, 120000 cases\n";
}
