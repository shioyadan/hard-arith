/* Copyright 2026 Ryota Shioya */
/* SPDX-License-Identifier: Apache-2.0 */

#include <math.h>
#include <quadmath.h>
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

uint32_t fp32_exp_ref(uint32_t input)
{
    uint32_t exponent = input & UINT32_C(0x7f800000);
    uint32_t fraction = input & UINT32_C(0x007fffff);
    uint32_t result;

    /* RTLと同じ特殊値規約へ合わせる。 */
    if (exponent == UINT32_C(0x7f800000)) {
        if (fraction != 0)
            return UINT32_C(0x7fc00000);
        return (input >> 31) ? 0 : UINT32_C(0x7f800000);
    }

    /* binary128でexpを計算してからbinary32へ丸める。 */
    result = float_to_bits((float)expq((__float128)bits_to_float(input)));
    /* 既定RTLに合わせ、binary32 subnormalは+0へflushする。 */
    return (result & UINT32_C(0x7f800000)) == 0 ? 0 : result;
}

uint64_t fp32_exp_faithful_bounds(uint32_t input)
{
    uint32_t exponent = input & UINT32_C(0x7f800000);
    uint32_t fraction = input & UINT32_C(0x007fffff);
    uint32_t lower;
    uint32_t upper;
    float x;
    float nearest;
    __float128 value;
    __float128 nearest_value;

    /* 特殊値では規定結果を上下限の両方へ置く。 */
    if (exponent == UINT32_C(0x7f800000)) {
        if (fraction != 0)
            lower = upper = UINT32_C(0x7fc00000);
        else if ((input >> 31) != 0)
            lower = upper = 0;
        else
            lower = upper = UINT32_C(0x7f800000);
        return ((uint64_t)upper << 32) | lower;
    }

    x = bits_to_float(input);
    value = expq((__float128)x);
    if (isinfq(value)) {
        lower = UINT32_C(0x7f7fffff);
        upper = UINT32_C(0x7f800000);
        return ((uint64_t)upper << 32) | lower;
    }
    if (value == 0) {
        lower = 0;
        upper = 1;
        return ((uint64_t)upper << 32) | lower;
    }

    nearest = (float)value;
    nearest_value = (__float128)nearest;
    if (nearest_value < value) {
        lower = float_to_bits(nearest);
        upper = float_to_bits(nextafterf(nearest, INFINITY));
    } else if (nearest_value > value) {
        lower = float_to_bits(nextafterf(nearest, -INFINITY));
        upper = float_to_bits(nearest);
    } else if (nearest == 1.0f && x > 0) {
        lower = float_to_bits(nearest);
        upper = float_to_bits(nextafterf(nearest, INFINITY));
    } else if (nearest == 1.0f && x < 0) {
        lower = float_to_bits(nextafterf(nearest, -INFINITY));
        upper = float_to_bits(nearest);
    } else {
        lower = upper = float_to_bits(nearest);
    }
    return ((uint64_t)upper << 32) | lower;
}

uint32_t fp32_exp_faithful_bounds_ambiguous(uint32_t input)
{
    uint32_t exponent = input & UINT32_C(0x7f800000);
    float x;
    __float128 value;
    float nearest;

    if (exponent == UINT32_C(0x7f800000) ||
        (input & UINT32_C(0x7fffffff)) == 0)
        return 0;
    x = bits_to_float(input);
    value = expq((__float128)x);
    if (isinfq(value) || value == 0)
        return 0;
    nearest = (float)value;
    if (nearest == 1.0f)
        return 0;
    return (__float128)nearest == value;
}

uint32_t fp32_reduction_boundary(int32_t index)
{
    __float128 boundary = (((__float128)index) + 0.5Q) *
                          logq(2.0Q) / 64.0Q;
    return float_to_bits((float)boundary);
}

#ifdef __cplusplus
}
#endif
