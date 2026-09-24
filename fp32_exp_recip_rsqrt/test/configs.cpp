// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <memory>
#include <string_view>
#include <vector>
#include <omp.h>
#include "VFP32ExpRecipRsqrtConfigs.h"
#include "verilated.h"

extern "C" uint32_t fp32_exp_recip_rsqrt_ref(uint32_t, uint32_t);
extern "C" uint32_t fp32_exp_recip_rsqrt_ref_ftz(uint32_t, uint32_t);

namespace {
using U128 = unsigned __int128;
constexpr uint32_t inf = 0x7f800000, nan = 0x7fc00000, fraction_mask = 0x7fffff;

// 係数や近似式に依存しない根系の厳密整数RNE。
uint32_t root_reference(uint32_t input, unsigned op, bool support) {
    const uint32_t sign = input & 0x80000000;
    int b = (input >> 23) & 255;
    uint32_t m = input & fraction_mask;
    if (b == 255 && m) return nan;
    if (b == 0 && (!m || !support)) return sign | inf;
    if (op == 4 && sign) return nan;
    if (b == 255) return sign;
    if (b == 0) {
        const int shift = std::countl_zero(m)-8;
        m <<= shift;
        b = 1-shift;
    } else {
        m |= 1u << 23;
    }
    uint32_t rounded;
    int exponent;
    if (op == 2) {
        const bool tiny = b >= 253;
        const uint64_t numerator = uint64_t{1} << (tiny ? 299-b : 47);
        const uint64_t lower = numerator/m, remainder = numerator%m;
        rounded = lower + (2*remainder > m || (2*remainder == m && (lower & 1)));
        if (tiny) return sign | (support || rounded >= (1u << 23) ? rounded : 0);
        exponent = 253-b;
    } else {
        const unsigned parity = 1-(b & 1);
        const U128 numerator = U128{1} << (71-parity);
        // binary64は探索の初期値だけに使い、上下とmidpointを整数で補正する。
        uint32_t lower = std::sqrt(std::ldexp(1.0, 71-parity)/m);
        while (U128{lower}*lower*m > numerator) --lower;
        while (U128{lower+1}*(lower+1)*m <= numerator) ++lower;
        const U128 midpoint = U128{2*lower+1}*(2*lower+1)*m;
        rounded = lower + (midpoint < 4*numerator || (midpoint == 4*numerator && (lower & 1)));
        const int half = b >= 0 ? b/2 : -((-b+1)/2);
        exponent = 189-half+parity;
    }
    if (rounded == (1u << 24)) { rounded >>= 1; ++exponent; }
    if (exponent >= 255) return sign | inf;
    return sign | (uint32_t(exponent) << 23) | (rounded & fraction_mask);
}

struct Stats {
    uint64_t checks = 0, comparisons = 0, monotonic_pairs = 0, baseline_checks = 0;
    std::array<uint64_t, 2> mismatches{};
    std::array<uint32_t, 2> maximum{};
};

[[noreturn]] void fail(const char* kind, uint32_t x, unsigned op, uint32_t actual, uint32_t expected) {
    std::cerr << kind << " x=" << std::hex << x << " op=" << op
              << " actual=" << actual << " expected=" << expected << '\n';
    std::exit(1);
}

void check(VFP32ExpRecipRsqrtConfigs& dut, uint32_t x, unsigned op, Stats& stats, bool crosscheck = false) {
    dut.x = x; dut.op = op; dut.eval();
    ++stats.checks;
#ifdef COMPARE_BASELINE
    if (dut.ftz != dut.baseline) fail("FTZ bit不一致", x, op, dut.ftz, dut.baseline);
    ++stats.baseline_checks;
#endif
    for (unsigned mode = 0; mode < 2; ++mode) {
        const uint32_t actual = mode ? dut.gradual : dut.ftz;
        const auto reference = mode ? fp32_exp_recip_rsqrt_ref : fp32_exp_recip_rsqrt_ref_ftz;
        const uint32_t expected = (op == 2 || op == 4) ? root_reference(x, op, mode) : reference(x, op);
        if (crosscheck && expected != reference(x, op)) fail("整数参照とbinary128不一致", x, op, expected, reference(x, op));
        const uint32_t mag = expected & 0x7fffffff;
        if (mag == 0 || mag >= inf) {
            if (actual != expected) fail("特殊値分類不一致", x, op, actual, expected);
        } else {
            if ((actual & 0x80000000) != (expected & 0x80000000)
                || (actual & 0x7fffffff) == 0 || (actual & 0x7fffffff) >= inf)
                fail("有限非zero分類不一致", x, op, actual, expected);
            const uint32_t error = actual > expected ? actual-expected : expected-actual;
            stats.maximum[mode] = std::max(stats.maximum[mode], error);
            stats.mismatches[mode] += error != 0;
            if (error > 1) fail("RNE step超過", x, op, actual, expected);
        }
        ++stats.comparisons;
    }
    // ONで値を保持する範囲以外は両設定が同じ出力になる。
    const uint32_t b = (x >> 23) & 255;
    const bool changed_domain = (op == 1 && (x & 0x80000000) && (dut.ftz == 0))
        || ((op == 2 || op == 4) && b == 0 && (x & fraction_mask))
        || (op == 2 && b >= 253 && b < 255);
    if (!changed_domain && dut.ftz != dut.gradual) fail("通常経路不一致", x, op, dut.gradual, dut.ftz);
}

void walk(VFP32ExpRecipRsqrtConfigs& dut, uint32_t first, uint32_t last, unsigned op,
          bool negative, Stats& stats) {
    std::array<uint32_t, 2> previous{};
    for (uint64_t x = first; x <= last; ++x) {
        check(dut, x, op, stats);
        const std::array<uint32_t, 2> current{dut.ftz, dut.gradual};
        if (x != first) {
            for (unsigned mode = 0; mode < 2; ++mode) {
                if (current[mode] > previous[mode]) fail("単調性逆行", x, op, current[mode], previous[mode]);
                ++stats.monotonic_pairs;
            }
        }
        previous = current;
        if (negative) {
            check(dut, uint32_t(x) | 0x80000000, op, stats);
            if (op == 2 && dut.gradual != (current[1] | 0x80000000))
                fail("recip符号対称性不一致", x, op, dut.gradual, current[1] | 0x80000000);
        }
    }
}

void report(const char* name, const Stats& s) {
    std::cout << name << " inputs=" << s.checks << " comparisons=" << s.comparisons
              << " max_steps_off=" << s.maximum[0] << " max_steps_on=" << s.maximum[1]
              << " rne_mismatches_off=" << s.mismatches[0] << " rne_mismatches_on=" << s.mismatches[1]
              << " monotonic_pairs=" << s.monotonic_pairs << " baseline_checks=" << s.baseline_checks
              << " violations=0 PASS" << std::endl;
}
} // namespace

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    // 旧RTLの指定時にはexp全入力のbit同値を並列検査できる。
    if (argc == 2 && std::string_view(argv[1]) == "--equivalence-exp-full") {
#ifndef COMPARE_BASELINE
        std::cerr << "BASELINE_RTLの指定が必要です\n"; return 2;
#else
        const int threads = std::min(16, omp_get_max_threads());
        std::vector<std::unique_ptr<VerilatedContext>> contexts;
        std::vector<std::unique_ptr<VFP32ExpRecipRsqrtConfigs>> models;
        for (int t = 0; t < threads; ++t) {
            contexts.emplace_back(std::make_unique<VerilatedContext>());
            models.emplace_back(std::make_unique<VFP32ExpRecipRsqrtConfigs>(contexts.back().get()));
        }
#pragma omp parallel num_threads(threads)
        {
            auto& dut = *models[omp_get_thread_num()];
            Verilated::threadContextp(contexts[omp_get_thread_num()].get());
            dut.op = 1;
#pragma omp for schedule(static)
            for (uint64_t x = 0; x < (uint64_t{1} << 32); ++x) {
                dut.x = x; dut.eval();
                if (dut.ftz != dut.baseline) fail("FTZ exp不一致", x, 1, dut.ftz, dut.baseline);
                // normal以上の結果とNaNはON側も同じ。subnormalは別の数値走査で検査する。
                if (dut.ftz && dut.gradual != dut.ftz) fail("exp通常経路不一致", x, 1, dut.gradual, dut.ftz);
            }
        }
        std::cout << "exp_equivalence inputs=4294967296 mismatches=0 PASS\n";
        return 0;
#endif
    }
    if (argc != 1) { std::cerr << "未知の引数です\n"; return 2; }
    VerilatedContext context;
    VFP32ExpRecipRsqrtConfigs dut{&context};
    Stats boundaries;
    for (unsigned op : {1u, 2u, 4u}) {
        for (unsigned b = 0; b < 256; ++b)
            for (uint32_t f : {0u, 1u, 2u, 0x1fffffu, 0x200000u, 0x200001u, 0x400000u, 0x7ffffeu, 0x7fffffu})
                for (uint32_t sign : {0u, 0x80000000u}) check(dut, sign | (b << 23) | f, op, boundaries, true);
        if (op != 1) {
            for (unsigned b = 1; b < 255; ++b) walk(dut, (b << 23)-1, (b << 23)+1, op, true, boundaries);
        }
    }
    for (unsigned op : {0u, 3u, 5u, 6u, 7u})
        for (uint32_t x : {0u, 1u, 0x007fffffu, 0x3f800000u, 0x7f800000u, 0xffc00001u}) check(dut, x, op, boundaries);
    report("boundaries", boundaries);
    for (unsigned op : {2u, 4u}) {
        Stats subnormal;
        walk(dut, 0, 0x00800000, op, true, subnormal);
        report(op == 2 ? "recip_subnormal_input" : "rsqrt_subnormal_input", subnormal);
        Stats normal;
        walk(dut, 0x3f800000, op == 2 ? 0x40000000 : 0x40800000, op, true, normal);
        report(op == 2 ? "recip_normal" : "rsqrt_normal", normal);
    }
    Stats tiny;
    walk(dut, 0x7e800000, 0x7f800000, 2, true, tiny);
    report("recip_subnormal_output", tiny);
    Stats exp;
    walk(dut, 0xc2ae0000, 0xc3010000, 1, false, exp); // -87から-129、飽和域まで連続検査。
    report("exp_underflow", exp);
    return 0;
}
