// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0
// 全残差で合格した候補の最大誤差と、境界単調性を同時に最適化する。
#include <algorithm>
#include <array>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <limits>
#include <vector>
#include <omp.h>
#include "model.hpp"
#include "coefficients.hpp"

struct Candidate { Coeff c; I worst,mismatch,first,last,cost,tie; int parent; };
constexpr I infinity=std::numeric_limits<I>::max()/4;

int main(int argc,char** argv) {
    const int radius=argc>1 ? std::atoi(argv[1]):2;
    if (radius<0 || radius>16) return 2;
    omp_set_num_threads(8);
    bool success=true;
    for (int bank=0;bank<3;++bank) {
        std::array<std::vector<Candidate>,128> rows;
#pragma omp parallel for schedule(dynamic)
        for (int row=0;row<128;++row) {
            std::vector<I> ref(65536),fine(65536);
            for (int off=0;off<65536;++off) {
                ref[off]=reference(bank,(row<<16)|off);
                fine[off]=reference(bank,(row<<16)|off,precision);
            }
            const Coeff base=baseline[bank][row];
            std::vector<Coeff> inputs{base};
            for (I da=-4;da<=4;++da) if (!((base.a+da)&1))
                for (I db=-radius;db<=radius;++db) for (I dc=-radius;dc<=radius;++dc)
                    inputs.push_back({base.a+da,base.b+db,base.c+dc});
            for (Coeff c:inputs) {
                if (c.c<0 || c.c>255) continue;
                bool valid=true;
                for (int off=0;off<65536;off+=127) {
                    if (bank!=2 && row==0 && off==0) continue;
                    if (std::abs(evaluate(c,off)-ref[off])>1) { valid=false;break; }
                }
                if (!valid) continue;
                I previous=I(1)<<24,worst=0,mismatch=0,first=0;
                for (int off=0;off<65536;++off) {
                    const bool exact=bank!=2 && row==0 && off==0;
                    const I y=exact ? I(1)<<24:evaluate(c,off);
                    const I error=std::abs(y-ref[off]);
                    if (error>1 || y>previous || (!exact && (y<(1<<23) || y>=(1<<24)))) {valid=false;break;}
                    worst=std::max(worst,std::abs(y*scale-fine[off]));
                    mismatch+=error;previous=y;
                    if (!off) first=y;
                }
                if (valid) rows[row].push_back({c,worst,mismatch,first,previous,infinity,infinity,-1});
            }
        }
        for (int mode=0;mode<2;++mode) {
            std::array<std::vector<Candidate>,128> allowed;
            for (int row=0;row<128;++row) for (auto c:rows[row]) {
                // mixedは参照量子化の半単位を足しても1.30 ULP以下。
                if (mode==0 ? !(c.c.a&1) : 10*(2*c.worst+1)<=26*scale)
                    allowed[row].push_back(c);
            }
            for (int row=0;row<128;++row) for (auto& c:allowed[row]) {
                const I local=mode==0 ? c.worst:(c.c.a&1);
                if (!row) { c.cost=local;c.tie=c.mismatch;continue; }
                for (int p=0;p<int(allowed[row-1].size());++p) {
                    const auto& prev=allowed[row-1][p];
                    if (prev.cost==infinity || prev.last<c.first) continue;
                    const I cost=mode==0 ? std::max(local,prev.cost):local+prev.cost;
                    const I tie=prev.tie+c.mismatch;
                    if (cost<c.cost || (cost==c.cost && tie<c.tie)) {
                        c.cost=cost;c.tie=tie;c.parent=p;
                    }
                }
            }
            int chosen=-1;I best=infinity,tie=infinity;
            for (int p=0;p<int(allowed[127].size());++p) {
                const auto& c=allowed[127][p];
                if (c.cost<best || (c.cost==best && c.tie<tie)) {best=c.cost;tie=c.tie;chosen=p;}
            }
            const int count=std::count_if(allowed.begin(),allowed.end(),[](const auto& r){return !r.empty();});
            std::cout<<"SEARCH bank="<<bank<<" mode="<<mode<<" radius="<<radius<<" rows="<<count
                     <<"/128 boundary_path="<<(chosen>=0)<<std::endl;
            if (chosen<0) {success=false;continue;}
            std::array<Coeff,128> coeffs;
            for (int row=127;row>=0;--row) {
                const auto& c=allowed[row][chosen];coeffs[row]=c.c;chosen=c.parent;
            }
            I worst=0,bad=0,reverse=0,range=0,exact_count=0,previous=I(1)<<24,odd=0;
            for (auto c:coeffs) odd+=c.a&1;
            for (int f=0;f<(1<<23);++f) {
                const bool exact=bank!=2 && f==0;
                const I y=exact ? I(1)<<24:evaluate(coeffs[f>>16],f&65535);
                const I r=reference(bank,f);
                bad+=std::abs(y-r)>1;exact_count+=y==r;reverse+=y>previous;
                range+=!exact && (y<(1<<23) || y>=(1<<24));previous=y;
                worst=std::max(worst,std::abs(y*scale-reference(bank,f,precision)));
            }
            std::cout<<"CHECK bank="<<bank<<" mode="<<mode<<" inputs=8388608 bad="<<bad
                     <<" reverse="<<reverse<<" range="<<range<<" exact="<<exact_count<<" odd_rows="<<odd
                     <<" worst_scaled="<<worst<<" error_upper_ulp="<<std::setprecision(12)
                     <<(double(worst)+0.5)/scale<<std::endl;
            success &= !bad && !reverse && !range;
            for (int row=0;row<128;++row) {
                const auto c=coeffs[row];
                std::cout<<"COEFF "<<bank<<' '<<mode<<' '<<row<<' '<<c.a<<' '<<c.b<<' '<<c.c<<'\n';
            }
            std::cout.flush();
        }
    }
    return success ? 0:1;
}
