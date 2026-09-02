// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0

#define _GNU_SOURCE
#include <math.h>
#include <stdint.h>
#include <string.h>

#ifdef __cplusplus
extern "C" {
#endif

static float bits_to_float(uint32_t bits)
{
    float value;
    memcpy(&value, &bits, sizeof(value));
    return value;
}

static uint32_t float_to_bits(float value)
{
    uint32_t bits;
    memcpy(&bits, &value, sizeof(bits));
    return bits;
}

static uint32_t ftz_input(uint32_t bits)
{
    return (bits & UINT32_C(0x7f800000)) == 0
        ? bits & UINT32_C(0x80000000) : bits;
}

static uint32_t ftz_output(_Float128 value)
{
    uint32_t bits;

    // 演算で生じたNaNは公開DUTの仕様に従って+Infとする。
    if (__builtin_isnan(value))
        return UINT32_C(0x7f800000);
    bits = float_to_bits((float)value);
    if ((bits & UINT32_C(0x7f800000)) == 0)
        return bits & UINT32_C(0x80000000);
    return bits;
}

static _Float128 exact_value(uint32_t input, uint32_t op)
{
    _Float128 x = (_Float128)bits_to_float(ftz_input(input));
    const _Float128 pi = acosf128(-1.0F128);
    _Float128 reduced;

    switch (op) {
    case UINT32_C(0x0001):
        return exp2f128(x);
    case UINT32_C(0x0002):
        return 1.0F128/x;
    case UINT32_C(0x0004):
        return 1.0F128/sqrtf128(x);
    case UINT32_C(0x0008):
        return sqrtf128(x);
    case UINT32_C(0x0010):
        return log2f128(x);
    case UINT32_C(0x0020):
        reduced = remainderf128(x, 2.0F128);
        if (reduced == 0.0F128 || fabsf128(reduced) == 1.0F128)
            return copysignf128(0.0F128, x);
        if (reduced == 0.5F128)
            return 1.0F128;
        if (reduced == -0.5F128)
            return -1.0F128;
        return sinf128(pi*reduced);
    case UINT32_C(0x0040):
        reduced = remainderf128(x, 2.0F128);
        if (reduced == 0.0F128)
            return 1.0F128;
        if (fabsf128(reduced) == 1.0F128)
            return -1.0F128;
        if (fabsf128(reduced) == 0.5F128)
            return 0.0F128;
        return cosf128(pi*reduced);
    default:
        return NAN;
    }
}

uint32_t fp32_elementary_ref(uint32_t input, uint32_t op)
{
    uint32_t exponent = input & UINT32_C(0x7f800000);
    uint32_t fraction = input & UINT32_C(0x007fffff);

    if (exponent == UINT32_C(0x7f800000) && fraction != 0)
        return UINT32_C(0x7fc00000);
    return ftz_output(exact_value(input, op));
}

double fp32_elementary_abs_error_units(uint32_t input, uint32_t op,
                                       uint32_t actual_bits)
{
    _Float128 reference = exact_value(input, op);
    _Float128 actual = (_Float128)bits_to_float(actual_bits);

    if (!__builtin_isfinite(reference) || !__builtin_isfinite(actual))
        return 0.0;
    return (double)(fabsf128(actual-reference)*8388608.0F128);
}

static uint32_t mix32(uint32_t value)
{
    value ^= value >> 16;
    value *= UINT32_C(0x7feb352d);
    value ^= value >> 15;
    value *= UINT32_C(0x846ca68b);
    return value ^ (value >> 16);
}

uint32_t fp32_elementary_test_input(uint32_t function_index, uint32_t ordinal)
{
    // opのbit順を変えても、関数ごとの回帰入力列は変えない。
    static const uint32_t function_seed[7] = {7, 1, 3, 2, 6, 4, 5};
    uint32_t random;
    uint32_t fraction;

    if (function_index >= 7)
        return 0;
    random = mix32(ordinal ^ (UINT32_C(0x9e3779b9) *
                              function_seed[function_index]));
    fraction = random & UINT32_C(0x007fffff);

    switch (function_index) {
    case 0: {
        long double unit = (long double)(random & UINT32_C(0x00ffffff)) /
                           16777215.0L;
        return float_to_bits((float)(-160.0L+290.0L*unit));
    }
    case 1:
        return random;
    case 2:
    case 3:
    case 4:
        return ((((random >> 24) % 254)+1) << 23) | fraction;
    case 5:
    case 6:
        return (random & UINT32_C(0x80000000)) |
               (((((random >> 24) % 21)+117) << 23) | fraction);
    default:
        return 0;
    }
}

uint32_t fp32_elementary_monotonic_input(uint32_t function_index,
                                         uint32_t ordinal, uint32_t count)
{
    long double unit;

    if (count <= 1)
        return 0;
    unit = (long double)ordinal/(long double)(count-1);
    switch (function_index) {
    case 1:
    case 2:
    case 3:
    case 4:
        return (uint32_t)(((uint64_t)ordinal*UINT64_C(0x7f800000)) /
                          (uint64_t)(count-1));
    case 0:
        return float_to_bits((float)(-160.0L+290.0L*unit));
    case 5:
        return float_to_bits((float)(-0.5L+unit));
    case 6:
        return float_to_bits((float)unit);
    default:
        return 0;
    }
}

#ifdef __cplusplus
}
#endif
