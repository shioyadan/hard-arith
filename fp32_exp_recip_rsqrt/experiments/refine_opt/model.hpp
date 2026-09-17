// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0
#pragma once
#include <cmath>
#include <cstdint>
using I=std::int64_t;
using U=unsigned __int128;
struct Coeff { I a,b,c; };
constexpr int precision=20;
constexpr I scale=I(1)<<precision;

// 参照値を2^-bits出力ULPへ厳密にRNEする。平方根近似は整数探索の初期値だけ。
inline I reference(int bank,int fraction,int bits=0) {
    const I m=(1<<23)+fraction;
    if (bank==0) {
        const U n=U(1)<<(47+bits);
        const I q=n/m,r=n%m;
        return q+(2*r>m || (2*r==m && (q&1)));
    }
    const U n=U(1)<<(71-(bank==2)+2*bits);
    I q=std::sqrt(static_cast<long double>(n)/m);
    while (U(q)*q*m>n) --q;
    while (U(q+1)*(q+1)*m<=n) ++q;
    const U midpoint=U(2*q+1)*(2*q+1)*m;
    return q+(midpoint<4*n || (midpoint==4*n && (q&1)));
}

inline I evaluate(Coeff c,int offset,bool single=true,I bias=131072) {
    const I d=2*(offset-32768);
    const I p=d*(2*c.b+((d*(2*c.c)+32768)>>15));
    if (single) return ((c.a<<17)+p+bias)>>18;
    const I value=4*c.a+((p+16384)>>15), high=value>>3,low=value&7;
    return high+(low>4 || (low==4 && (high&1)));
}
