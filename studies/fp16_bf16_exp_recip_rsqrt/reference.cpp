// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0
// 候補の固定小数点モデルと独立したbinary128参照値。
#include <math.h>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <initializer_list>

static uint16_t pack(__float128 y, int f, int b) {
    const unsigned sign = __builtin_signbit(y) ? 0x8000 : 0;
    const unsigned inf = ((1u << b) - 1) << f;
    const int bias = (1 << (b - 1)) - 1;
    if (__builtin_isnan(y)) return inf | (1 << (f - 1));
    if (__builtin_isinf(y)) return sign | inf;
    y = __builtin_fabsf128(y);
    if (y == 0) return sign;
    int e;
    frexpf128(y, &e);
    --e;
    if (e > bias) return sign | inf;
    if (e < -bias - f - 2) return sign;
    // subnormalの格子まで丸めてからFTZする。
    if (e < 1 - bias) e = 1 - bias;
    const __float128 scaled = scalbnf128(y, f - e);
    const __float128 lower = floorf128(scaled);
    unsigned m = static_cast<unsigned>(lower);
    const __float128 tail = scaled - lower;
    if (tail > 0.5 || (tail == 0.5 && (m & 1))) ++m;
    if (m < (1u << f)) return sign;
    if (m == (2u << f)) { m >>= 1; ++e; }
    if (e > bias) return sign | inf;
    return sign | ((e + bias) << f) | (m - (1 << f));
}

extern "C" unsigned reference16(unsigned u, unsigned code, unsigned f) {
    const int b = 15-f, bias = (1 << (b-1))-1;
    const unsigned inf = ((1u << b)-1) << f;
    const unsigned nan = inf | (1 << (f-1));
    const unsigned s = u & 0x8000, a = u & 0x7fff;
    const int e = a >> f;
    if (code != 1 && code != 2 && code != 4) return nan;
    if (a > inf) return nan;
    if (e == 0) return code == 1 ? bias << f : s | inf;
    if (a == inf) return code == 1 ? (s ? 0 : inf) : code == 2 ? s : s ? nan : 0;
    if (code == 4 && s) return nan;
    const __float128 x = scalbnf128(static_cast<__float128>(
        (1 << f) + (a & ((1 << f)-1))), e-bias-static_cast<int>(f)) * (s ? -1 : 1);
    // 両形式のoverflow／FTZより十分外側でexp計算を省く。
    __float128 y;
    if (code == 1) y = x > 1024 ? __builtin_huge_valf128() : x < -1024 ? 0 : expf128(x);
    else if (code == 2) y = 1/x;
    else y = 1/sqrtf128(x);
    return pack(y, f, b);
}

#ifndef REFERENCE_DPI
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    FILE *out = std::fopen(argv[1], "wb");
    if (!out) return 2;
    for (int f : {10, 7}) {
        for (int op = 0; op < 3; ++op) {
            for (unsigned u = 0; u < 65536; ++u) {
                const uint16_t v = reference16(u, 1u << op, f);
                const unsigned char bytes[] = {static_cast<unsigned char>(v),
                    static_cast<unsigned char>(v >> 8)};
                if (std::fwrite(bytes, 1, 2, out) != 2) return 2;
            }
        }
    }
    return std::fclose(out) == 0 ? 0 : 2;
}
#endif
