// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0

#include "VFP32Log2Lite.h"
#include "verilated.h"

#include <algorithm>
#include <bit>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <quadmath.h>
#include <string>
#include <vector>

#include <omp.h>

struct Metrics {
    uint64_t checked = 0;
    uint64_t correct = 0;
    uint64_t violations = 0;
    uint64_t monotonic_violations = 0;
    uint32_t max_ulp = 0;
    __float128 max_abs_units = 0;
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
    const uint32_t end = UINT32_C(0x40000000);
    const uint64_t count = (uint64_t)end-begin;
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
        VFP32Log2Lite dut;
        uint32_t previous = 0;

        for (uint64_t offset = chunk_begin; offset < chunk_end; ++offset) {
            const uint32_t input = begin+(uint32_t)offset;
            const __float128 exact = log2q((__float128)bits_to_float(input));
            const uint32_t expected = float_to_bits((float)exact);
            dut.x = input;
            dut.eval();
            const uint32_t actual = dut.result;
            const uint32_t actual_ordered = ordered(actual);
            const uint32_t expected_ordered = ordered(expected);
            const uint32_t ulp = actual_ordered >= expected_ordered
                ? actual_ordered-expected_ordered
                : expected_ordered-actual_ordered;
            const __float128 abs_units = fabsq(
                (__float128)bits_to_float(actual)-exact
            )*8388608.0Q;

            if (!nonempty[(size_t)tid]) {
                first_output[(size_t)tid] = actual_ordered;
                nonempty[(size_t)tid] = true;
            } else if (actual_ordered < previous) {
                ++metrics.monotonic_violations;
            }
            previous = actual_ordered;
            last_output[(size_t)tid] = actual_ordered;

            ++metrics.checked;
            if (actual == expected)
                ++metrics.correct;
            if (ulp > 2 && abs_units > 4.0Q) {
                ++metrics.violations;
                if (metrics.first_failure == 0)
                    metrics.first_failure = input;
            }
            if (ulp > metrics.max_ulp)
                metrics.max_ulp = ulp;
            if (abs_units > metrics.max_abs_units) {
                metrics.max_abs_units = abs_units;
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
        total.monotonic_violations += metrics.monotonic_violations;
        total.max_ulp = std::max(total.max_ulp, metrics.max_ulp);
        if (metrics.max_abs_units > total.max_abs_units) {
            total.max_abs_units = metrics.max_abs_units;
            total.worst_input = metrics.worst_input;
        }
        if (total.first_failure == 0 && metrics.first_failure != 0)
            total.first_failure = metrics.first_failure;
    }
    for (int tid = 1; tid < threads; ++tid)
        if (nonempty[(size_t)tid] && nonempty[(size_t)(tid-1)]
                && first_output[(size_t)tid] < last_output[(size_t)(tid-1)])
            ++total.monotonic_violations;

    char max_abs_text[64];
    quadmath_snprintf(max_abs_text, sizeof(max_abs_text), "%.9Qf",
                      total.max_abs_units);
    std::printf(
        "checked=%llu RNE_match=%llu violations=%llu max_ulp=%u "
        "max_abs_error=%s*2^-23 monotonic_violations=%llu\n",
        (unsigned long long)total.checked,
        (unsigned long long)total.correct,
        (unsigned long long)total.violations,
        total.max_ulp,
        max_abs_text,
        (unsigned long long)total.monotonic_violations
    );
    std::printf("worst=%08x first_failure=%08x\n",
                total.worst_input, total.first_failure);
    return total.violations == 0 && total.monotonic_violations == 0
        ? EXIT_SUCCESS : EXIT_FAILURE;
}
