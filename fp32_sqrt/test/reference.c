/* Copyright 2026 Ryota Shioya and Toru Koizumi */
/* SPDX-License-Identifier: Apache-2.0 */

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

static uint32_t floor_sqrt_u64(uint64_t value)
{
    uint32_t low = UINT32_C(1) << 23;
    uint32_t high = UINT32_C(1) << 24;

    while (low < high) {
        const uint32_t middle = low + (high - low + 1) / 2;
        if ((uint64_t)middle * middle <= value)
            low = middle;
        else
            high = middle - 1;
    }
    return low;
}

static uint32_t fp32_sqrt_positive_normal(
    uint32_t input, int round_to_nearest)
{
    const uint32_t exponent = (input >> 23) & UINT32_C(0xff);
    const uint32_t fraction = input & UINT32_C(0x007fffff);
    const uint32_t parity = (~exponent) & 1;
    const uint32_t significand = UINT32_C(0x00800000) | fraction;
    const uint64_t radicand =
        (uint64_t)significand << (23 + parity);
    uint32_t root = floor_sqrt_u64(radicand);
    const uint64_t remainder = radicand - (uint64_t)root * root;
    const uint32_t output_exponent =
        (exponent + UINT32_C(127) - parity) >> 1;

    /* sqrt(N)>root+0.5は、整数NではN-root^2>rootと同値である。 */
    if (round_to_nearest && remainder > root)
        ++root;
    return (output_exponent << 23)
         | (root & UINT32_C(0x007fffff));
}

uint32_t fp32_sqrt_ref(uint32_t input)
{
    const uint32_t sign = input >> 31;
    const uint32_t exponent = (input >> 23) & UINT32_C(0xff);
    const uint32_t fraction = input & UINT32_C(0x007fffff);

    if (exponent == UINT32_C(0xff)) {
        if (fraction != 0 || sign != 0)
            return UINT32_C(0x7fc00000);
        return UINT32_C(0x7f800000);
    }
    if (exponent == 0)
        return sign << 31;
    if (sign != 0)
        return UINT32_C(0x7fc00000);
    return fp32_sqrt_positive_normal(input, 1);
}

uint64_t fp32_sqrt_faithful_bounds(uint32_t input)
{
    const uint32_t sign = input >> 31;
    const uint32_t exponent = (input >> 23) & UINT32_C(0xff);
    const uint32_t fraction = input & UINT32_C(0x007fffff);
    uint32_t lower;
    uint32_t upper;

    if (exponent == 0 || exponent == UINT32_C(0xff) || sign != 0) {
        lower = upper = fp32_sqrt_ref(input);
        return ((uint64_t)upper << 32) | lower;
    }

    {
        const uint32_t parity = (~exponent) & 1;
        const uint32_t significand = UINT32_C(0x00800000) | fraction;
        const uint64_t radicand =
            (uint64_t)significand << (23 + parity);
        const uint32_t root = floor_sqrt_u64(radicand);
        const uint64_t square = (uint64_t)root * root;
        const uint32_t output_exponent =
            (exponent + UINT32_C(127) - parity) >> 1;
        lower = (output_exponent << 23)
              | (root & UINT32_C(0x007fffff));
        upper = square == radicand ? lower : lower + 1;
    }
    return ((uint64_t)upper << 32) | lower;
}

#ifdef __cplusplus
}
#endif
