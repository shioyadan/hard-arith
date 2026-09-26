// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <cstdint>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <mpfr.h>

inline float as_float(uint32_t bits) {
    float value;
    std::memcpy(&value, &bits, sizeof(value));
    return value;
}

inline uint32_t as_bits(float value) {
    uint32_t bits;
    std::memcpy(&bits, &value, sizeof(bits));
    return bits;
}

// 77-bit桁合わせやsticky処理を共有しない、厳密な高精度積和の参照。
class Reference {
    mpfr_t a_, b_, c_, result_, lower_, upper_, midpoint_;
public:
    Reference() {
        static_assert(sizeof(float) == 4 && std::numeric_limits<float>::is_iec559);
        mpfr_inits2(640, a_, b_, c_, result_, lower_, upper_, midpoint_, static_cast<mpfr_ptr>(nullptr));
    }
    ~Reference() {
        mpfr_clears(a_, b_, c_, result_, lower_, upper_, midpoint_, static_cast<mpfr_ptr>(nullptr));
    }
    Reference(const Reference&) = delete;
    Reference& operator=(const Reference&) = delete;

    uint32_t operator()(uint32_t a, uint32_t b, uint32_t c, unsigned mode = 0) {
        if (mode > 4) return 0x7fc00000;
        const mpfr_rnd_t modes[] = {MPFR_RNDN, MPFR_RNDZ, MPFR_RNDD, MPFR_RNDU, MPFR_RNDN};
        const mpfr_rnd_t rounding = modes[mode];
        mpfr_set_flt(a_, as_float(a), MPFR_RNDN);
        mpfr_set_flt(b_, as_float(b), MPFR_RNDN);
        mpfr_set_flt(c_, as_float(c), MPFR_RNDN);
        // 相殺で厳密にzeroとなる場合の符号にも、指定モードを反映する。
        const int inexact = mpfr_fma(result_, a_, b_, c_, rounding);
        if (mpfr_nan_p(result_)) return 0x7fc00000;
        if (inexact != 0) throw std::runtime_error("MPFR積和の精度が不足している");
        const uint32_t nearest = as_bits(mpfr_get_flt(result_, rounding));
        if (mode != 4 || mpfr_inf_p(result_) || mpfr_zero_p(result_)) return nearest;

        // RMMは隣接浮動小数点数の厳密な中点と比較する。RTLのGRSは使わない。
        const uint32_t toward_zero = as_bits(mpfr_get_flt(result_, MPFR_RNDZ));
        const uint32_t lower_bits = toward_zero & 0x7fffffff;
        const uint32_t upper_bits = lower_bits + 1;
        mpfr_set_flt(lower_, as_float(lower_bits), MPFR_RNDN);
        if (upper_bits == 0x7f800000)
            mpfr_set_ui_2exp(upper_, 1, 128, MPFR_RNDN); // overflow境界の仮想的な隣接値
        else
            mpfr_set_flt(upper_, as_float(upper_bits), MPFR_RNDN);
        mpfr_add(midpoint_, lower_, upper_, MPFR_RNDN);
        mpfr_div_2ui(midpoint_, midpoint_, 1, MPFR_RNDN);
        return mpfr_cmpabs(result_, midpoint_) == 0 ? (toward_zero & 0x80000000) | upper_bits : nearest;
    }
};
