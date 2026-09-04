// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0

#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
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

static uint32_t flush_subnormal_output(uint32_t bits)
{
    return (bits & UINT32_C(0x7f800000)) == 0
        ? bits & UINT32_C(0x80000000) : bits;
}

uint32_t fp32_exp_recip_rsqrt_ref(uint32_t input, uint32_t op)
{
    const uint32_t sign = input & UINT32_C(0x80000000);
    const uint32_t exponent = input & UINT32_C(0x7f800000);
    const uint32_t fraction = input & UINT32_C(0x007fffff);
    const float x = bits_to_float(input);

    if (exponent == UINT32_C(0x7f800000) && fraction != 0)
        return UINT32_C(0x7fc00000);

    switch (op) {
    case UINT32_C(0x1):
        if (exponent == UINT32_C(0x7f800000))
            return sign != 0 ? 0 : UINT32_C(0x7f800000);
        return float_to_bits((float)expf128((_Float128)x));
    case UINT32_C(0x2):
        if (exponent == UINT32_C(0x7f800000))
            return sign;
        if (exponent == 0)
            return sign | UINT32_C(0x7f800000);
        return flush_subnormal_output(
            float_to_bits((float)(1.0F128/(_Float128)x)));
    case UINT32_C(0x4):
        if (exponent == 0)
            return sign | UINT32_C(0x7f800000);
        if (sign != 0)
            return UINT32_C(0x7fc00000);
        if (exponent == UINT32_C(0x7f800000))
            return 0;
        return float_to_bits((float)(1.0F128/sqrtf128((_Float128)x)));
    default:
        return UINT32_C(0x7fc00000);
    }
}

uint32_t fp32_exp_recip_rsqrt_ref_ftz(uint32_t input, uint32_t op)
{
    const uint32_t result = fp32_exp_recip_rsqrt_ref(input, op);
    return op == UINT32_C(0x1) ? flush_subnormal_output(result) : result;
}

/* binary128参照値を挟む二つのbinary32値を{upper, lower}で返す。 */
uint64_t fp32_exp_recip_rsqrt_faithful_bounds(uint32_t input, uint32_t op)
{
    const uint32_t sign = input & UINT32_C(0x80000000);
    const uint32_t exponent = input & UINT32_C(0x7f800000);
    const uint32_t fraction = input & UINT32_C(0x007fffff);
    const float x = bits_to_float(input);
    _Float128 value;
    float nearest;
    uint32_t lower;
    uint32_t upper;

    if (exponent == UINT32_C(0x7f800000) || op == 0
        || (op & (op-1)) != 0) {
        lower = upper = fp32_exp_recip_rsqrt_ref(input, op);
        return ((uint64_t)upper << 32) | lower;
    }

    switch (op) {
    case UINT32_C(0x1):
        value = expf128((_Float128)x);
        break;
    case UINT32_C(0x2):
        if (exponent == 0) {
            lower = upper = sign | UINT32_C(0x7f800000);
            return ((uint64_t)upper << 32) | lower;
        }
        value = 1.0F128/(_Float128)x;
        break;
    case UINT32_C(0x4):
        if (exponent == 0 || sign != 0) {
            lower = upper = fp32_exp_recip_rsqrt_ref(input, op);
            return ((uint64_t)upper << 32) | lower;
        }
        value = 1.0F128/sqrtf128((_Float128)x);
        break;
    default:
        lower = upper = UINT32_C(0x7fc00000);
        return ((uint64_t)upper << 32) | lower;
    }

    if (__builtin_isinf_sign(value) != 0) {
        lower = value < 0 ? UINT32_C(0xff800000) : UINT32_C(0x7f7fffff);
        upper = value < 0 ? UINT32_C(0xff7fffff) : UINT32_C(0x7f800000);
        return ((uint64_t)upper << 32) | lower;
    }
    if (value == 0) {
        lower = sign != 0 && op == UINT32_C(0x2)
            ? UINT32_C(0x80000001) : 0;
        upper = sign != 0 && op == UINT32_C(0x2)
            ? UINT32_C(0x80000000) : 1;
        return ((uint64_t)upper << 32) | lower;
    }

    nearest = (float)value;
    if ((_Float128)nearest < value) {
        lower = float_to_bits(nearest);
        upper = float_to_bits(nextafterf(nearest, INFINITY));
    } else if ((_Float128)nearest > value) {
        lower = float_to_bits(nextafterf(nearest, -INFINITY));
        upper = float_to_bits(nearest);
    } else if (op == UINT32_C(0x1) && nearest == 1.0f && x > 0) {
        lower = float_to_bits(nearest);
        upper = float_to_bits(nextafterf(nearest, INFINITY));
    } else if (op == UINT32_C(0x1) && nearest == 1.0f && x < 0) {
        lower = float_to_bits(nextafterf(nearest, -INFINITY));
        upper = float_to_bits(nearest);
    } else {
        lower = upper = float_to_bits(nearest);
    }
    return ((uint64_t)upper << 32) | lower;
}

/* binary128で厳密な上下関係を判定できないexp入力だけを識別する。 */
uint32_t fp32_exp_recip_rsqrt_faithful_bounds_ambiguous(
    uint32_t input, uint32_t op)
{
    const uint32_t exponent = input & UINT32_C(0x7f800000);
    const float x = bits_to_float(input);
    _Float128 value;
    float nearest;

    if (op != UINT32_C(0x1) || exponent == UINT32_C(0x7f800000)
        || (input & UINT32_C(0x7fffffff)) == 0)
        return 0;
    value = expf128((_Float128)x);
    if (__builtin_isinf_sign(value) != 0 || value == 0)
        return 0;
    nearest = (float)value;
    if (nearest == 1.0f)
        return 0;
    return (_Float128)nearest == value;
}

static uint32_t mix32(uint32_t value)
{
    value ^= value >> 16;
    value *= UINT32_C(0x7feb352d);
    value ^= value >> 15;
    value *= UINT32_C(0x846ca68b);
    return value ^ (value >> 16);
}

uint32_t fp32_exp_recip_rsqrt_test_input(uint32_t function_index,
                                         uint32_t ordinal)
{
    static const uint32_t function_seed[3] = {7, 1, 3};
    uint32_t random;

    if (function_index >= 3)
        return 0;
    random = mix32(ordinal ^ (UINT32_C(0x9e3779b9) *
                              function_seed[function_index]));
    if (function_index == 0) {
        const long double unit =
            (long double)(random & UINT32_C(0x00ffffff))/16777215.0L;
        return float_to_bits((float)(-160.0L+290.0L*unit));
    }
    if (function_index == 1)
        return random;
    return ((((random >> 24) % 254)+1) << 23)
         | (random & UINT32_C(0x007fffff));
}

uint32_t fp32_exp_recip_rsqrt_monotonic_input(uint32_t function_index,
                                              uint32_t ordinal,
                                              uint32_t count)
{
    if (count <= 1)
        return 0;
    if (function_index == 0) {
        const long double unit = (long double)ordinal/(long double)(count-1);
        return float_to_bits((float)(-160.0L+290.0L*unit));
    }
    return (uint32_t)(((uint64_t)ordinal*UINT64_C(0x7f800000)) /
                      (uint64_t)(count-1));
}

#ifdef __cplusplus
}
#endif
