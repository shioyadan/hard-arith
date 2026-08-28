/* Copyright 2026 Ryota Shioya */
/* SPDX-License-Identifier: Apache-2.0 */

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

static uint32_t reciprocal_magnitude(uint32_t input, int round_to_nearest)
{
    const uint32_t exponent = (input >> 23) & UINT32_C(0xff);
    const uint32_t fraction = input & UINT32_C(0x007fffff);
    uint32_t result_exponent;
    uint64_t significand;
    uint64_t quotient;
    uint64_t remainder;

    /* zeroとsubnormal入力はFTZ入力規約によりzeroとして扱う。 */
    if (exponent == 0)
        return UINT32_C(0x7f800000);
    if (exponent == UINT32_C(0xff)) {
        if (fraction != 0)
            return UINT32_C(0x7fc00000);
        return 0;
    }

    /* 逆数がsubnormalになる範囲はsigned zeroへflushする。 */
    if (exponent == UINT32_C(0xfe)
        || (exponent == UINT32_C(0xfd) && fraction != 0))
        return 0;

    /* 2のべき乗は仮数が厳密に1.0のまま指数だけを反転する。 */
    if (fraction == 0) {
        result_exponent = UINT32_C(254) - exponent;
        return result_exponent << 23;
    }

    /*
     * m=significand*2^-23に対する正規化済み出力仮数は2/mである。
     * binary32 significandの厳密値は2^47/significandなので、整数除算だけで
     * 直下値、直上値、RNE値を決められる。
     */
    significand = UINT64_C(0x00800000) | fraction;
    quotient = (UINT64_C(1) << 47) / significand;
    remainder = (UINT64_C(1) << 47) % significand;
    if (round_to_nearest) {
        const uint64_t twice_remainder = remainder << 1;
        if (twice_remainder > significand
            || (twice_remainder == significand && (quotient & 1) != 0))
            ++quotient;
    }
    result_exponent = UINT32_C(253) - exponent;
    return (result_exponent << 23)
         | (uint32_t)(quotient & UINT64_C(0x007fffff));
}

uint32_t fp32_recip_ref(uint32_t input)
{
    const uint32_t exponent = input & UINT32_C(0x7f800000);
    const uint32_t fraction = input & UINT32_C(0x007fffff);
    const uint32_t sign = input & UINT32_C(0x80000000);
    uint32_t magnitude;

    if (exponent == UINT32_C(0x7f800000) && fraction != 0)
        return UINT32_C(0x7fc00000);
    magnitude = reciprocal_magnitude(input, 1);
    return sign | magnitude;
}

uint64_t fp32_recip_faithful_bounds(uint32_t input)
{
    const uint32_t exponent = (input >> 23) & UINT32_C(0xff);
    const uint32_t fraction = input & UINT32_C(0x007fffff);
    const uint32_t sign = input & UINT32_C(0x80000000);
    uint32_t lower;
    uint32_t upper;

    /* 特殊値、FTZ範囲、2のべき乗では規定結果が一意である。 */
    if (exponent == 0
        || exponent == UINT32_C(0xff)
        || exponent == UINT32_C(0xfe)
        || (exponent == UINT32_C(0xfd) && fraction != 0)
        || fraction == 0) {
        lower = upper = fp32_recip_ref(input);
        return ((uint64_t)upper << 32) | lower;
    }

    {
        const uint64_t significand = UINT64_C(0x00800000) | fraction;
        const uint64_t numerator = UINT64_C(1) << 47;
        const uint64_t quotient = numerator / significand;
        const uint64_t remainder = numerator % significand;
        const uint32_t result_exponent = UINT32_C(253) - exponent;
        const uint32_t lower_magnitude =
            (result_exponent << 23)
            | (uint32_t)(quotient & UINT64_C(0x007fffff));
        const uint32_t upper_magnitude = remainder == 0
            ? lower_magnitude : lower_magnitude + 1;

        if (sign == 0) {
            lower = lower_magnitude;
            upper = upper_magnitude;
        } else {
            lower = sign | upper_magnitude;
            upper = sign | lower_magnitude;
        }
    }
    return ((uint64_t)upper << 32) | lower;
}

#ifdef __cplusplus
}
#endif
