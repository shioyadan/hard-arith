// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <cstdint>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <mpfr.h>

inline double as_double(uint64_t bits) {
    double value;
    std::memcpy(&value, &bits, sizeof(value));
    return value;
}

inline uint64_t as_bits(double value) {
    uint64_t bits;
    std::memcpy(&bits, &value, sizeof(bits));
    return bits;
}

// DUTの桁合わせ、先頭検出、sticky処理を共有しない厳密な高精度積和。
class Reference {
    mpfr_t a_, b_, c_, result_, lower_, upper_, midpoint_;
public:
    Reference() {
        static_assert(sizeof(double) == 8 && std::numeric_limits<double>::is_iec559 &&
                      std::numeric_limits<double>::digits == 53);
        // 最小非zero積は2^-2148、有限入力同士の積和の絶対値は2^2048未満。
        // この全格子を保持できる4352 bitとし、実際の積和もinexact=0を要求する。
        mpfr_inits2(4352, a_, b_, c_, result_, lower_, upper_, midpoint_, static_cast<mpfr_ptr>(nullptr));
    }
    ~Reference() {
        mpfr_clears(a_, b_, c_, result_, lower_, upper_, midpoint_, static_cast<mpfr_ptr>(nullptr));
    }
    Reference(const Reference&) = delete;
    Reference& operator=(const Reference&) = delete;

    uint64_t operator()(uint64_t a, uint64_t b, uint64_t c, unsigned mode = 0) {
        if (mode > 4) return UINT64_C(0x7ff8000000000000);
        const mpfr_rnd_t modes[] = {MPFR_RNDN, MPFR_RNDZ, MPFR_RNDD, MPFR_RNDU, MPFR_RNDN};
        const mpfr_rnd_t rounding = modes[mode];
        mpfr_set_d(a_, as_double(a), MPFR_RNDN);
        mpfr_set_d(b_, as_double(b), MPFR_RNDN);
        mpfr_set_d(c_, as_double(c), MPFR_RNDN);
        // 厳密な相殺でzeroになる場合の符号にも、指定モードを反映する。
        const int inexact = mpfr_fma(result_, a_, b_, c_, rounding);
        if (mpfr_nan_p(result_)) return UINT64_C(0x7ff8000000000000);
        if (inexact != 0) throw std::runtime_error("MPFR積和の精度が不足している");
        const uint64_t nearest = as_bits(mpfr_get_d(result_, rounding));
        if (mode != 4 || mpfr_inf_p(result_) || mpfr_zero_p(result_)) return nearest;

        // RMMは隣接binary64の中点と厳密比較する。RTLのGRS判定は使わない。
        const uint64_t toward_zero = as_bits(mpfr_get_d(result_, MPFR_RNDZ));
        const uint64_t lower_bits = toward_zero & UINT64_C(0x7fffffffffffffff);
        const uint64_t upper_bits = lower_bits + 1;
        mpfr_set_d(lower_, as_double(lower_bits), MPFR_RNDN);
        if (upper_bits == UINT64_C(0x7ff0000000000000))
            mpfr_set_ui_2exp(upper_, 1, 1024, MPFR_RNDN); // overflow境界の仮想的な隣接値
        else
            mpfr_set_d(upper_, as_double(upper_bits), MPFR_RNDN);
        mpfr_add(midpoint_, lower_, upper_, MPFR_RNDN);
        mpfr_div_2ui(midpoint_, midpoint_, 1, MPFR_RNDN);
        return mpfr_cmpabs(result_, midpoint_) == 0 ?
            (toward_zero & UINT64_C(0x8000000000000000)) | upper_bits : nearest;
    }
};
