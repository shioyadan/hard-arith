/* Copyright 2026 Ryota Shioya and Toru Koizumi */
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

uint32_t fp32_log2_ref(uint32_t input)
{
    uint32_t exponent = input & UINT32_C(0x7f800000);
    uint32_t fraction = input & UINT32_C(0x007fffff);

    if (exponent == UINT32_C(0x7f800000)) {
        if (fraction != 0 || (input >> 31) != 0)
            return UINT32_C(0x7fc00000);
        return UINT32_C(0x7f800000);
    }
    if ((input & UINT32_C(0x7fffffff)) == 0)
        return UINT32_C(0xff800000);
    if ((input >> 31) != 0)
        return UINT32_C(0x7fc00000);

    return float_to_bits((float)log2q((__float128)bits_to_float(input)));
}

uint64_t fp32_log2_faithful_bounds(uint32_t input)
{
    uint32_t expected = fp32_log2_ref(input);
    uint32_t exponent = input & UINT32_C(0x7f800000);
    uint32_t fraction = input & UINT32_C(0x007fffff);
    uint32_t lower;
    uint32_t upper;
    __float128 exact;
    float nearest;
    __float128 nearest_value;

    if (exponent == UINT32_C(0x7f800000) ||
        (input & UINT32_C(0x7fffffff)) == 0 ||
        (input >> 31) != 0) {
        lower = upper = expected;
        return ((uint64_t)upper << 32) | lower;
    }

    exact = log2q((__float128)bits_to_float(input));
    nearest = (float)exact;
    nearest_value = (__float128)nearest;
    if (nearest_value < exact) {
        lower = float_to_bits(nearest);
        upper = float_to_bits(nextafterf(nearest, INFINITY));
    } else if (nearest_value > exact) {
        lower = float_to_bits(nextafterf(nearest, -INFINITY));
        upper = float_to_bits(nearest);
    } else {
        lower = upper = float_to_bits(nearest);
    }
    return ((uint64_t)upper << 32) | lower;
}

uint32_t fp32_log2_lite_ref(uint32_t input)
{
    uint32_t exponent = input & UINT32_C(0x7f800000);
    uint32_t fraction = input & UINT32_C(0x007fffff);

    if (exponent == UINT32_C(0x7f800000)) {
        if (fraction != 0 || (input >> 31) != 0)
            return UINT32_C(0x7fc00000);
        return UINT32_C(0x7f800000);
    }
    if (exponent == 0)
        return UINT32_C(0xff800000);
    if ((input >> 31) != 0)
        return UINT32_C(0x7fc00000);
    return float_to_bits((float)log2q((__float128)bits_to_float(input)));
}

double fp32_log2_lite_abs_error_units(uint32_t input, uint32_t actual_bits)
{
    uint32_t exponent = input & UINT32_C(0x7f800000);
    __float128 exact;
    __float128 actual;

    if (exponent == 0 || exponent == UINT32_C(0x7f800000)
            || (input >> 31) != 0)
        return 0.0;
    exact = log2q((__float128)bits_to_float(input));
    actual = (__float128)bits_to_float(actual_bits);
    return (double)(fabsq(actual-exact)*8388608.0Q);
}

#ifdef __cplusplus
}
#endif
