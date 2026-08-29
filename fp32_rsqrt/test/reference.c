/* Copyright 2026 Ryota Shioya and Toru Koizumi */
/* SPDX-License-Identifier: Apache-2.0 */

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef __uint128_t uint128_t;

static uint128_t square_times_significand(
    uint32_t value, uint32_t significand)
{
    return (uint128_t)value * value * significand;
}

/* floor(sqrt(numerator/significand))を整数比較だけで求める。 */
static uint32_t floor_output_significand(
    uint128_t numerator, uint32_t significand)
{
    uint32_t low = UINT32_C(1) << 23;
    uint32_t high = UINT32_C(1) << 24;

    while (low < high) {
        const uint32_t middle = low + (high - low + 1) / 2;
        if (square_times_significand(middle, significand) <= numerator)
            low = middle;
        else
            high = middle - 1;
    }
    return low;
}

static uint32_t pack_significand(
    uint32_t base_exponent, uint32_t significand)
{
    if (significand == (UINT32_C(1) << 24))
        return (base_exponent + 1) << 23;
    return (base_exponent << 23)
         | (significand & UINT32_C(0x007fffff));
}

static uint32_t fp32_rsqrt_positive_normal(
    uint32_t input, int round_to_nearest)
{
    const uint32_t exponent = (input >> 23) & UINT32_C(0xff);
    const uint32_t fraction = input & UINT32_C(0x007fffff);
    const uint32_t parity = (~exponent) & 1;
    const uint32_t significand = UINT32_C(0x00800000) | fraction;
    const uint128_t numerator = (uint128_t)1 << (71 - parity);
    const uint32_t base_exponent =
        (UINT32_C(380) - exponent - (exponent & 1)) >> 1;
    uint32_t lower = floor_output_significand(numerator, significand);

    if (round_to_nearest
        && square_times_significand(lower, significand) != numerator) {
        const uint32_t twice_lower_plus_one = 2 * lower + 1;
        const uint128_t midpoint_square =
            (uint128_t)twice_lower_plus_one * twice_lower_plus_one
            * significand;
        const uint128_t four_numerator = numerator << 2;
        if (midpoint_square < four_numerator
            || (midpoint_square == four_numerator && (lower & 1) != 0))
            ++lower;
    }
    return pack_significand(base_exponent, lower);
}

uint32_t fp32_rsqrt_ref(uint32_t input)
{
    const uint32_t sign = input >> 31;
    const uint32_t exponent = (input >> 23) & UINT32_C(0xff);
    const uint32_t fraction = input & UINT32_C(0x007fffff);

    if (exponent == UINT32_C(0xff)) {
        if (fraction != 0 || sign != 0)
            return UINT32_C(0x7fc00000);
        return 0;
    }
    if (exponent == 0)
        return sign != 0 ? UINT32_C(0xff800000) : UINT32_C(0x7f800000);
    if (sign != 0)
        return UINT32_C(0x7fc00000);
    return fp32_rsqrt_positive_normal(input, 1);
}

uint64_t fp32_rsqrt_faithful_bounds(uint32_t input)
{
    const uint32_t sign = input >> 31;
    const uint32_t exponent = (input >> 23) & UINT32_C(0xff);
    const uint32_t fraction = input & UINT32_C(0x007fffff);
    uint32_t lower;
    uint32_t upper;

    if (exponent == 0 || exponent == UINT32_C(0xff) || sign != 0) {
        lower = upper = fp32_rsqrt_ref(input);
        return ((uint64_t)upper << 32) | lower;
    }

    {
        const uint32_t parity = (~exponent) & 1;
        const uint32_t significand = UINT32_C(0x00800000) | fraction;
        const uint128_t numerator = (uint128_t)1 << (71 - parity);
        const uint32_t base_exponent =
            (UINT32_C(380) - exponent - (exponent & 1)) >> 1;
        const uint32_t lower_significand =
            floor_output_significand(numerator, significand);
        const int exact = square_times_significand(
            lower_significand, significand) == numerator;

        lower = pack_significand(base_exponent, lower_significand);
        upper = exact ? lower : pack_significand(
            base_exponent, lower_significand + 1);
    }
    return ((uint64_t)upper << 32) | lower;
}

#ifdef __cplusplus
}
#endif
