// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0
// 根系全仮数の整数参照と量子化Hornerを比較する。探索は有限近傍に限る。
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <vector>
#include <omp.h>
using I = std::int64_t;
using U = unsigned __int128;
struct Coeff { I a, b, c; };
#include "coefficients.hpp"

// 2^24/mまたは2^24/sqrt(m*2^p)を厳密にRNEする。sqrtは探索開始値だけに使う。
I reference(int bank, int fraction) {
    const I m = (1<<23)+fraction;
    if (bank == 0) {
        const I n = I(1)<<47, q = n/m, r = n%m;
        return q+(2*r > m || (2*r == m && (q&1)));
    }
    const U n = U(1)<<(71-(bank == 2));
    I q = std::sqrt(static_cast<long double>(n)/m);
    while (U(q)*q*m > n) --q;
    while (U(q+1)*(q+1)*m <= n) ++q;
    const U midpoint = U(2*q+1)*(2*q+1)*m;
    return q+(midpoint < 4*n || (midpoint == 4*n && (q&1)));
}

I evaluate(Coeff c, int offset, int mode) {
    const I d = 2*(offset-32768);
    const I h = 2*c.b+((d*(2*c.c)+32768)>>15);
    const I p = d*h;
    if (mode == 1) return ((c.a<<17)+p+131072)>>18;
    const I value = 4*c.a+((p+(mode == 2 ? 0 : 16384))>>15);
    const I high = value>>3, low = value&7;
    return high+(low > 4 || (low == 4 && (high&1)));
}

struct Stats {
    I count=0, bad=0, reverse=0, range=0, exact=0, changed=0, maxstep=0;
    I firstbad=-1, firstreverse=-1, minimum=I(1)<<60, maximum=0;
};

Stats check(int bank, const std::array<Coeff,128>& coeffs, int mode) {
    Stats s;
    I previous = I(1)<<24;
    for (int f=0; f<(1<<23); ++f) {
        const bool exact = bank != 2 && f == 0;
        const I y = exact ? I(1)<<24 : evaluate(coeffs[f>>16], f&65535, mode);
        const I ref = reference(bank, f);
        const I original = exact ? I(1)<<24 : evaluate(baseline[bank][f>>16], f&65535, 0);
        const I step = std::abs(y-ref);
        ++s.count;
        s.exact += y == ref;
        s.changed += y != original;
        s.maxstep = std::max(s.maxstep, step);
        if (step > 1) { ++s.bad; if (s.firstbad < 0) s.firstbad=f; }
        if (y > previous) { ++s.reverse; if (s.firstreverse < 0) s.firstreverse=f; }
        if (!exact) {
            s.range += y < (1<<23) || y >= (1<<24);
            s.minimum=std::min(s.minimum,y); s.maximum=std::max(s.maximum,y);
        }
        previous=y;
    }
    return s;
}

void print(int bank, const char* mode, Stats s) {
    std::cout << "CHECK bank=" << bank << " mode=" << mode << " inputs=" << s.count
        << " maxstep=" << s.maxstep << " bad=" << s.bad << " reverse=" << s.reverse
        << " range=" << s.range << " exact=" << s.exact << " changed=" << s.changed
        << " min=" << s.minimum << " max=" << s.maximum
        << " firstbad=" << s.firstbad << " firstreverse=" << s.firstreverse << std::endl;
}

int main(int argc, char** argv) {
    const int radius = argc > 1 ? std::atoi(argv[1]) : 2;
    if (radius < 0 || radius > 16) return 2;
    omp_set_num_threads(8);
    for (int bank=0; bank<3; ++bank) {
        std::array<Coeff,128> coefficients;
        std::copy(std::begin(baseline[bank]),std::end(baseline[bank]),coefficients.begin());
        for (int mode=0; mode<3; ++mode) print(bank, std::array{"baseline","single-round","root-floor"}[mode], check(bank,coefficients,mode));
        for (int mode=0; mode<2; ++mode) {
            std::array<int,128> found{};
            struct Candidate { Coeff c; I score, first, last, cost; int parent; };
            std::array<std::vector<Candidate>,128> candidates;
#pragma omp parallel for schedule(dynamic)
            for (int row=0; row<128; ++row) {
                std::vector<I> ref(65536);
                for (int off=0; off<65536; ++off) ref[off]=reference(bank,(row<<16)|off);
                const Coeff base=baseline[bank][row];
                for (I da=-4; da<=4; ++da) {
                    const I a=base.a+da;
                    if (a&1) continue;
                    for (I db=-radius; db<=radius; ++db) for (I dc=-radius; dc<=radius; ++dc) {
                        Coeff c{a,base.b+db,base.c+dc};
                        if (c.c < 0 || c.c > 255) continue;
                        bool valid=true;
                        // まず疎格子で不成立案を除く。合格候補は必ず全65536点を確認する。
                        for (int off=0; off<65536; off+=127) {
                            if (bank != 2 && row == 0 && off == 0) continue;
                            if (std::abs(evaluate(c,off,mode)-ref[off])>1) { valid=false; break; }
                        }
                        if (!valid) continue;
                        I score=0, previous=I(1)<<24;
                        for (int off=0; off<65536; ++off) {
                            const bool exact=bank != 2 && row == 0 && off == 0;
                            const I y=exact ? I(1)<<24 : evaluate(c,off,mode);
                            const I err=std::abs(y-ref[off]);
                            if (err>1 || y>previous || (!exact && (y<(1<<23) || y>=(1<<24)))) {valid=false;break;}
                            previous=y; score+=err;
                        }
                        if (valid) {
                            const I first=(bank != 2 && row == 0) ? I(1)<<24 : evaluate(c,0,mode);
                            candidates[row].push_back({c,score,first,previous,std::numeric_limits<I>::max()/4,-1});
                            found[row]=1;
                        }
                    }
                }
            }
            const int count=std::count(found.begin(),found.end(),1);
            // 行内だけで最良を選ばず、境界も単調となる組合せを動的計画法で選ぶ。
            const I infinity=std::numeric_limits<I>::max()/4;
            for (int row=0;row<128;++row) for (auto& c:candidates[row]) {
                if (row==0) {c.cost=c.score;continue;}
                for (int p=0;p<int(candidates[row-1].size());++p) {
                    const auto& previous=candidates[row-1][p];
                    if (previous.last >= c.first && previous.cost+c.score<c.cost) {
                        c.cost=previous.cost+c.score;c.parent=p;
                    }
                }
            }
            int chosen=-1;
            I best=infinity;
            for (int p=0;p<int(candidates[127].size());++p) if (candidates[127][p].cost<best) {
                best=candidates[127][p].cost;chosen=p;
            }
            const bool path=chosen>=0;
            std::copy(std::begin(baseline[bank]),std::end(baseline[bank]),coefficients.begin());
            if (path) for (int row=127;row>=0;--row) {
                const auto& c=candidates[row][chosen];
                coefficients[row]=c.c;chosen=c.parent;
            }
            std::cout << "SEARCH bank=" << bank << " mode=" << mode << " radius=" << radius << " rows=" << count << "/128 failed=";
            for (int row=0;row<128;++row) if (!found[row]) std::cout << row << ',';
            std::cout << " boundary_path=" << path << std::endl;
            print(bank, mode == 0 ? "c0-q24" : "c0-q24-single",check(bank,coefficients,mode));
            for (int row=0;row<128;++row) {
                Coeff c=coefficients[row];
                std::cout << "COEFF " << bank << ' ' << mode << ' ' << row << ' ' << found[row]
                    << ' ' << c.a << ' ' << c.b << ' ' << c.c << '\n';
            }
            std::cout.flush();
        }
    }
}
