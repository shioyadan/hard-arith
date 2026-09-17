// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0
// expは基準RTLと全bit比較。根系は全仮数・全指数境界で整数モデルと比較する。
#include <array>
#include <cstdint>
#include <iostream>
#include <memory>
#include <omp.h>
#include "VVerify.h"
#include "verilated.h"
using I=std::int64_t;
struct Coeff { I a,b,c; };
#include "verify-coefficients.hpp"
constexpr std::array modes{0,0,1,2,0,1};
std::array<std::uint32_t,6> outputs(const VVerify& d) { return {d.v0,d.v1,d.v2,d.v3,d.v4,d.v5}; }

std::uint32_t model(std::uint32_t x,int op,int variant) {
    const unsigned sign=x>>31, e=(x>>23)&255, f=x&0x7fffff, parity=(~e)&1;
    constexpr unsigned nan=0x7fc00000;
    if ((op!=2 && op!=4) || (e==255 && f)) return nan;
    if (op==2 && e==255) return sign<<31;
    if (e==0) return (sign<<31)|0x7f800000;
    if (op==4 && sign) return nan;
    if (op==4 && e==255) return 0;
    const bool exact=f==0 && (op==2 || parity==0);
    if (op==2 && (e==254 || (e==253 && !exact))) return sign<<31;
    const unsigned exponent=op==2 ? 253-e+exact : 189-(e>>1)+parity+exact;
    const int bank=op==2 ? 0 : 1+parity;
    const Coeff c=coefficients[variant][bank][f>>16];
    const I d=2*(I(f&65535)-32768);
    const I h=2*c.b+((d*(2*c.c)+32768)>>15), p=d*h;
    I mant;
    if (modes[variant]==1) mant=((c.a<<17)+p+131072)>>18;
    else {
        const I value=4*c.a+((p+(modes[variant]==2 ? 0 : 16384))>>15);
        mant=(value>>3)+((value&7)>4 || ((value&7)==4 && ((value>>3)&1)));
    }
    return (op==2 ? sign<<31 : 0)|(exponent<<23)|(exact ? 0 : (unsigned(mant)&0x7fffff));
}

int main() {
    omp_set_num_threads(8);
    std::uint64_t exp_count=0,root_count=0,boundary_count=0,bad=0,reverse=0;
    const double start=omp_get_wtime();
#pragma omp parallel reduction(+:exp_count,root_count,boundary_count,bad,reverse)
    {
        auto ctx=std::make_unique<VerilatedContext>();ctx->threads(1);
        VVerify dut(ctx.get());
#pragma omp for schedule(dynamic)
        for (unsigned block=0;block<4096;++block) {
            dut.op=1;
            for (unsigned j=0;j<(1u<<20);++j) {
                dut.x=(block<<20)|j;dut.eval();
                for (auto y:outputs(dut)) bad+=y!=dut.v0;
                ++exp_count;
            }
        }
#pragma omp for schedule(dynamic)
        for (unsigned block=0;block<48;++block) {
            const unsigned group=block/8;
            const unsigned sign=group<2 ? group : (group-2)/2;
            const unsigned e=group<2 ? 127 : 127+((group-2)&1);
            const unsigned first=(sign<<31)|(e<<23)|((block&7)<<20);
            dut.op=group<2 ? 2 : 4;
            for (unsigned j=0;j<(1u<<20);++j) {
                dut.x=first+j;dut.eval();
                const auto values=outputs(dut);
                for (int v=0;v<6;++v) bad+=values[v]!=model(dut.x,dut.op,v);
                ++root_count;
            }
        }
#pragma omp for schedule(dynamic)
        for (unsigned tag=0;tag<4096;++tag) {
            dut.op=tag/512;
            for (unsigned fraction:{0u,1u,2u,0x3fffffu,0x400000u,0x7ffffdu,0x7ffffeu,0x7fffffu}) {
                dut.x=((tag&511)<<23)|fraction;dut.eval();
                for (int v=0;v<6;++v) {
                    bad+=dut.op==1 ? outputs(dut)[v]!=dut.v0 : outputs(dut)[v]!=model(dut.x,dut.op,v);
                    if ((dut.op==2 || dut.op==4) && (dut.x>>31)==0 && dut.x<0x7f800000) {
                        reverse+=model(dut.x+1,dut.op,v)>model(dut.x,dut.op,v);
                    }
                }
                ++boundary_count;
            }
        }
    }
    const bool counts=exp_count==(1ull<<32) && root_count==50331648 && boundary_count==32768;
    std::cout << ((counts && !bad && !reverse) ? "PASS" : "FAIL")
        << ": exp=" << exp_count << " root=" << root_count << " boundary=" << boundary_count
        << " variants=6 mismatches=" << bad << " boundary_reversals=" << reverse
        << " seconds=" << omp_get_wtime()-start << std::endl;
    return counts && !bad && !reverse ? 0 : 1;
}
