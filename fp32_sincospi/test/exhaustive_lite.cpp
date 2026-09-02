// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0

#include "VFP32SinCosPiLite.h"
#include "verilated.h"

#include <algorithm>
#include <bit>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

#include <omp.h>

struct Metrics {
    uint64_t checked = 0;
    uint64_t correct = 0;
    uint64_t violations = 0;
    uint64_t monotonic = 0;
    uint32_t max_monotonic_ulp = 0;
    long double max_error_units = 0;
    uint32_t worst_input = 0;
    uint32_t first_failure = 0;
};

static float bits_to_float(uint32_t bits)
{
    return std::bit_cast<float>(bits);
}

static uint32_t float_to_bits(float value)
{
    return std::bit_cast<uint32_t>(value);
}

static uint32_t ordered(uint32_t value)
{
    return value >> 31 ? ~value : (value ^ UINT32_C(0x80000000));
}

int main(int argc, char **argv)
{
    int threads = omp_get_max_threads();
    for (int i = 1; i < argc; ++i) {
        const std::string argument(argv[i]);
        const std::string prefix("--threads=");
        if (argument.rfind(prefix, 0) == 0)
            threads = std::max(1, std::atoi(argument.c_str()+prefix.size()));
    }

    const uint32_t begin = UINT32_C(0x3f000000);
    const uint32_t end = UINT32_C(0x3f800000);
    // [0.5, 1]のbinary32を2 patternずつ進めると、縮約後の全Q23位相を
    // 一度ずつ逆順に得られる。各位相について丸め前区間の両端も検査する。
    const uint64_t count = ((uint64_t)end-begin)/2+1;
    const long double pi = acosl(-1.0L);
    std::vector<Metrics> local((size_t)threads);
    std::vector<uint32_t> first_output((size_t)threads);
    std::vector<uint32_t> last_output((size_t)threads);
    std::vector<bool> nonempty((size_t)threads, false);

#pragma omp parallel num_threads(threads)
    {
        const int tid = omp_get_thread_num();
        const uint64_t chunk_begin = count*(uint64_t)tid/(uint64_t)threads;
        const uint64_t chunk_end = count*(uint64_t)(tid+1)/(uint64_t)threads;
        Metrics &metrics = local[(size_t)tid];
        VFP32SinCosPiLite dut;
        uint32_t previous = 0;

        for (uint64_t offset = chunk_begin; offset < chunk_end; ++offset) {
            const uint32_t input = begin+2*(uint32_t)offset;
            const long double x = (long double)bits_to_float(input);
            const long double reduced = 1.0L-x;
            const long double half_phase_lsb = ldexpl(1.0L, -24);
            const long double reduced_low =
                std::max(0.0L, reduced-half_phase_lsb);
            const long double reduced_high =
                std::min(0.5L, reduced+half_phase_lsb);
            dut.x = input;
            dut.select_cos = 0;
            dut.eval();
            const uint32_t actual_bits = dut.result;
            const long double actual =
                fabsl((long double)bits_to_float(actual_bits));
            const long double exact = sinl(pi*reduced);
            const long double error_low =
                fabsl(actual-sinl(pi*reduced_low))*8388608.0L;
            const long double error_high =
                fabsl(actual-sinl(pi*reduced_high))*8388608.0L;
            const long double error = std::max(error_low, error_high);
            const uint32_t actual_ordered = ordered(actual_bits);

            if (!nonempty[(size_t)tid]) {
                first_output[(size_t)tid] = actual_ordered;
                nonempty[(size_t)tid] = true;
            } else if (actual_ordered > previous) {
                ++metrics.monotonic;
                metrics.max_monotonic_ulp = std::max(
                    metrics.max_monotonic_ulp, actual_ordered-previous);
            }
            previous = actual_ordered;
            last_output[(size_t)tid] = actual_ordered;

            ++metrics.checked;
            if (actual_bits == float_to_bits((float)exact))
                ++metrics.correct;
            if (error > 4.000001L) {
                ++metrics.violations;
                if (metrics.first_failure == 0)
                    metrics.first_failure = input;
            }
            if (error > metrics.max_error_units) {
                metrics.max_error_units = error;
                metrics.worst_input = input;
            }
        }
        dut.final();
    }

    Metrics total;
    for (const Metrics &metrics : local) {
        total.checked += metrics.checked;
        total.correct += metrics.correct;
        total.violations += metrics.violations;
        total.monotonic += metrics.monotonic;
        total.max_monotonic_ulp = std::max(
            total.max_monotonic_ulp, metrics.max_monotonic_ulp);
        if (metrics.max_error_units > total.max_error_units) {
            total.max_error_units = metrics.max_error_units;
            total.worst_input = metrics.worst_input;
        }
        if (total.first_failure == 0 && metrics.first_failure != 0)
            total.first_failure = metrics.first_failure;
    }
    for (int tid = 1; tid < threads; ++tid)
        if (nonempty[(size_t)tid] && nonempty[(size_t)(tid-1)]
                && first_output[(size_t)tid] > last_output[(size_t)(tid-1)]) {
            ++total.monotonic;
            total.max_monotonic_ulp = std::max(
                total.max_monotonic_ulp,
                first_output[(size_t)tid]-last_output[(size_t)(tid-1)]);
        }

    std::printf(
        "phase_points=%llu RNE_match=%llu violations=%llu "
        "max_abs_error=%.9Lf*2^-23 "
        "monotonic=%llu max_monotonic_ulp=%u\n",
        (unsigned long long)total.checked,
        (unsigned long long)total.correct,
        (unsigned long long)total.violations,
        total.max_error_units,
        (unsigned long long)total.monotonic,
        total.max_monotonic_ulp);
    std::printf("worst=%08x first_failure=%08x\n",
                total.worst_input, total.first_failure);

    // Liteの契約は絶対誤差であり、table境界での単調性は診断値として報告する。
    if (total.violations != 0)
        return EXIT_FAILURE;
    return EXIT_SUCCESS;
}
