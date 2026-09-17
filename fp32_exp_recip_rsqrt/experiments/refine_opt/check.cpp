// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0
// 公開版とのexp全入力一致、根系の整数モデル・独立参照、全指数端点を確認する。
#include <algorithm>
#include <array>
#include <iomanip>
#include <iostream>
#include <memory>
#include <omp.h>
#include "VVerify.h"
#include "verilated.h"
#include "model.hpp"
#include "verify-coefficients.hpp"
std::array<std::uint32_t,6> outputs(const VVerify& d) {return {d.v0,d.v1,d.v2,d.v3,d.v4,d.v5};}

I mantissa(int v,int bank,unsigned f) {
    return bank!=2 && !f ? I(1)<<24 : evaluate(coefficients[v][bank][f>>16],f&65535,v!=0,v==3 ? 0:131072);
}

std::uint32_t model(std::uint32_t x,int op,int v) {
    const unsigned sign=x>>31,e=(x>>23)&255,f=x&0x7fffff,parity=(~e)&1;
    constexpr unsigned nan=0x7fc00000;
    if ((op!=2 && op!=4) || (e==255 && f)) return nan;
    if (op==2 && e==255) return sign<<31;
    if (e==0) return (sign<<31)|0x7f800000;
    if (op==4 && sign) return nan;
    if (op==4 && e==255) return 0;
    const bool exact=f==0 && (op==2 || parity==0);
    if (op==2 && (e==254 || (e==253 && !exact))) return sign<<31;
    const unsigned exponent=op==2 ? 253-e+exact : 189-(e>>1)+parity+exact;
    const int bank=op==2 ? 0:1+parity;
    return (op==2 ? sign<<31:0)|(exponent<<23)|(exact ? 0:(unsigned(mantissa(v,bank,f))&0x7fffff));
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
            const unsigned sign=group<2 ? group:(group-2)/2;
            const unsigned e=group<2 ? 127:127+((group-2)&1);
            const unsigned first=(sign<<31)|(e<<23)|((block&7)<<20);
            dut.op=group<2 ? 2:4;
            for (unsigned j=0;j<(1u<<20);++j) {
                dut.x=first+j;dut.eval();
                const auto values=outputs(dut);
                for (int v=0;v<6;++v) bad+=values[v]!=model(dut.x,dut.op,v);
                bad+=values[1]!=values[2];bad+=values[1]!=values[3];
                ++root_count;
            }
        }
#pragma omp for schedule(dynamic)
        for (unsigned tag=0;tag<4096;++tag) {
            dut.op=tag/512;
            for (unsigned fraction:{0u,1u,2u,0x3fffffu,0x400000u,0x7ffffdu,0x7ffffeu,0x7fffffu}) {
                dut.x=((tag&511)<<23)|fraction;dut.eval();
                for (int v=0;v<6;++v) {
                    bad+=dut.op==1 ? outputs(dut)[v]!=dut.v0:outputs(dut)[v]!=model(dut.x,dut.op,v);
                    if ((dut.op==2 || dut.op==4) && (dut.x>>31)==0 && dut.x<0x7f800000)
                        reverse+=model(dut.x+1,dut.op,v)>model(dut.x,dut.op,v);
                }
                ++boundary_count;
            }
        }
    }
    // 係数とRTLに依存しない整数参照で、全仮数の精度と単調性を検査する。
    struct Stats {I bad=0,reverse=0,range=0,exact=0,worst=0,maxstep=0;};
    std::array<std::array<Stats,3>,6> numeric{};
#pragma omp parallel for schedule(dynamic)
    for (int task=0;task<18;++task) {
        const int v=task/3,bank=task%3;
        auto& s=numeric[v][bank];I previous=I(1)<<24;
        for (int f=0;f<(1<<23);++f) {
            const I y=mantissa(v,bank,f),r=reference(bank,f),step=std::abs(y-r);
            s.maxstep=std::max(s.maxstep,step);s.bad+=step>1;s.exact+=y==r;
            s.reverse+=y>previous;previous=y;
            s.range+=!(bank!=2 && !f) && (y<(1<<23) || y>=(1<<24));
            s.worst=std::max(s.worst,std::abs(y*scale-reference(bank,f,precision)));
        }
    }
    for (int v=0;v<6;++v) for (int bank=0;bank<3;++bank) {
        const auto s=numeric[v][bank];bad+=s.bad+s.range;reverse+=s.reverse;
        std::cout<<"NUMERIC variant="<<v<<" bank="<<bank<<" inputs=8388608 maxstep="<<s.maxstep
                 <<" bad="<<s.bad<<" reverse="<<s.reverse<<" range="<<s.range<<" exact="<<s.exact
                 <<" worst_scaled="<<s.worst<<" error_upper_ulp="<<std::setprecision(12)
                 <<(double(s.worst)+0.5)/scale<<'\n';
    }
    const bool counts=exp_count==(1ull<<32) && root_count==50331648 && boundary_count==32768;
    std::cout<<((counts && !bad && !reverse) ? "PASS":"FAIL")<<": exp="<<exp_count
             <<" root="<<root_count<<" boundary="<<boundary_count
             <<" variants=6 mismatches="<<bad<<" boundary_reversals="<<reverse
             <<" seconds="<<omp_get_wtime()-start<<std::endl;
    return counts && !bad && !reverse ? 0:1;
}
