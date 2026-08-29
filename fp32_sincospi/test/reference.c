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

static __float128 fp32_sincospi_exact(uint32_t input, uint32_t select_cos,
                                     uint32_t *exact_bits)
{
    uint32_t exponent = input & UINT32_C(0x7f800000);
    uint32_t fraction = input & UINT32_C(0x007fffff);
    uint32_t input_sign = input >> 31;
    __float128 magnitude;
    __float128 phase;
    __float128 selected_phase;
    __float128 reduced;
    __float128 value;
    uint32_t result_sign;

    *exact_bits = UINT32_C(0xffffffff);
    if (exponent == UINT32_C(0x7f800000)) {
        *exact_bits = UINT32_C(0x7fc00000);
        return nanq("");
    }

    magnitude = (__float128)bits_to_float(input & UINT32_C(0x7fffffff));
    if (magnitude == 0) {
        *exact_bits = select_cos ? UINT32_C(0x3f800000)
                                 : (input & UINT32_C(0x80000000));
        return select_cos ? 1.0Q : copysignq(0.0Q, input_sign ? -1.0Q : 1.0Q);
    }

    /* binary32は2^24以上で偶数整数なので、ここでは位相を直接確定できる。 */
    if ((input & UINT32_C(0x7f800000)) >= UINT32_C(0x4b800000)) {
        *exact_bits = select_cos ? UINT32_C(0x3f800000)
                                 : (input & UINT32_C(0x80000000));
        return select_cos ? 1.0Q : copysignq(0.0Q, input_sign ? -1.0Q : 1.0Q);
    }

    phase = fmodq(magnitude, 2.0Q);
    selected_phase = phase + (select_cos ? 0.5Q : 0.0Q);
    if (selected_phase >= 2.0Q)
        selected_phase -= 2.0Q;
    result_sign = (selected_phase >= 1.0Q) ^ (input_sign && !select_cos);
    reduced = fmodq(selected_phase, 1.0Q);
    if (reduced > 0.5Q)
        reduced = 1.0Q-reduced;

    if (reduced == 0.0Q) {
        *exact_bits = result_sign << 31;
        return copysignq(0.0Q, result_sign ? -1.0Q : 1.0Q);
    }
    if (reduced == 0.5Q) {
        *exact_bits = (result_sign << 31) | UINT32_C(0x3f800000);
        return result_sign ? -1.0Q : 1.0Q;
    }

    value = sinq(acosq(-1.0Q)*reduced);
    return result_sign ? -value : value;
}

uint32_t fp32_sincospi_ref(uint32_t input, uint32_t select_cos)
{
    uint32_t exact_bits;
    __float128 value = fp32_sincospi_exact(input, select_cos, &exact_bits);
    if (exact_bits != UINT32_C(0xffffffff))
        return exact_bits;
    return float_to_bits((float)value);
}

uint64_t fp32_sincospi_faithful_bounds(uint32_t input, uint32_t select_cos)
{
    uint32_t exact_bits;
    uint32_t lower;
    uint32_t upper;
    __float128 value = fp32_sincospi_exact(input, select_cos, &exact_bits);
    float nearest;
    __float128 nearest_value;

    if (exact_bits != UINT32_C(0xffffffff)) {
        lower = upper = exact_bits;
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
    } else {
        lower = upper = float_to_bits(nearest);
    }
    return ((uint64_t)upper << 32) | lower;
}

double fp32_sincospi_abs_error_units(uint32_t input, uint32_t select_cos,
                                     uint32_t actual_bits)
{
    uint32_t exact_bits;
    __float128 exact = fp32_sincospi_exact(input, select_cos, &exact_bits);
    __float128 actual;

    if (exact_bits != UINT32_C(0xffffffff))
        return actual_bits == exact_bits ? 0.0 : INFINITY;

    actual = (__float128)bits_to_float(actual_bits);
    return (double)(fabsq(actual-exact)*8388608.0Q);
}

#ifdef __cplusplus
}
#endif
