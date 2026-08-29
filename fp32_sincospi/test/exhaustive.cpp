// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0

#include "VFP32SinCosPi.h"
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

struct Bounds {
    uint32_t nearest;
    uint32_t lower;
    uint32_t upper;
};

struct Metrics {
    uint64_t checked = 0;
    uint64_t correct = 0;
    uint64_t violations = 0;
    uint64_t monotonic = 0;
    uint32_t max_ulp = 0;
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

static uint32_t ulp_distance(uint32_t actual, uint32_t expected)
{
    return actual >= expected ? actual-expected : expected-actual;
}

static Bounds reference_bounds(uint32_t input)
{
    const long double x = (long double)bits_to_float(input);
    const long double exact = sinl(acosl(-1.0L)*x);
    const float nearest_value = (float)exact;
    const long double rounded = (long double)nearest_value;
    Bounds result;
    result.nearest = float_to_bits(nearest_value);
    if (rounded < exact) {
        result.lower = result.nearest;
        result.upper = float_to_bits(nextafterf(nearest_value, INFINITY));
    } else if (rounded > exact) {
        result.lower = float_to_bits(nextafterf(nearest_value, -INFINITY));
        result.upper = result.nearest;
    } else {
        result.lower = result.nearest;
        result.upper = result.nearest;
    }
    return result;
}

static void merge_metrics(Metrics &target, const Metrics &source)
{
    target.checked += source.checked;
    target.correct += source.correct;
    target.violations += source.violations;
    target.monotonic += source.monotonic;
    if (source.max_ulp > target.max_ulp) {
        target.max_ulp = source.max_ulp;
        target.worst_input = source.worst_input;
    }
    if (target.first_failure == 0 && source.first_failure != 0)
        target.first_failure = source.first_failure;
}

static Metrics scan_range(uint32_t begin, uint32_t end, int threads,
                          bool increasing = true)
{
    std::vector<Metrics> local_metrics((size_t)threads);
    std::vector<uint32_t> first_output((size_t)threads);
    std::vector<uint32_t> last_output((size_t)threads);
    std::vector<bool> nonempty((size_t)threads, false);
    const uint64_t count = (uint64_t)end-begin;

#pragma omp parallel num_threads(threads)
    {
        const int tid = omp_get_thread_num();
        const uint64_t chunk_begin = count*(uint64_t)tid/(uint64_t)threads;
        const uint64_t chunk_end = count*(uint64_t)(tid+1)/(uint64_t)threads;
        Metrics &metrics = local_metrics[(size_t)tid];
        VFP32SinCosPi dut;
        uint32_t previous = 0;

        dut.select_cos = 0;
        for (uint64_t offset = chunk_begin; offset < chunk_end; ++offset) {
            const uint32_t input = begin+(uint32_t)offset;
            const Bounds bounds = reference_bounds(input);
            dut.x = input;
            dut.eval();
            const uint32_t actual = dut.result;
            const uint32_t distance = ulp_distance(actual, bounds.nearest);

            if (!nonempty[(size_t)tid]) {
                first_output[(size_t)tid] = actual;
                nonempty[(size_t)tid] = true;
            } else if (increasing ? actual < previous : actual > previous) {
                ++metrics.monotonic;
            }
            previous = actual;
            last_output[(size_t)tid] = actual;

            ++metrics.checked;
            if (actual == bounds.nearest)
                ++metrics.correct;
            if (actual != bounds.lower && actual != bounds.upper) {
                ++metrics.violations;
                if (metrics.first_failure == 0)
                    metrics.first_failure = input;
            }
            if (distance > metrics.max_ulp) {
                metrics.max_ulp = distance;
                metrics.worst_input = input;
            }
        }
        dut.final();
    }

    Metrics result;
    for (const Metrics &metrics : local_metrics)
        merge_metrics(result, metrics);
    for (int tid = 1; tid < threads; ++tid) {
        if (!nonempty[(size_t)tid] || !nonempty[(size_t)(tid-1)])
            continue;
        if (increasing
                ? first_output[(size_t)tid] < last_output[(size_t)(tid-1)]
                : first_output[(size_t)tid] > last_output[(size_t)(tid-1)])
            ++result.monotonic;
    }
    return result;
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

    Metrics total;
    const Metrics correction = scan_range(UINT32_C(0x38800000),
                                          UINT32_C(0x3b800000), threads);
    const Metrics subnormal = scan_range(UINT32_C(0x00000001),
                                         UINT32_C(0x00800000), threads);
    const Metrics central = scan_range(UINT32_C(0x3b800000),
                                       UINT32_C(0x3c000000), threads);
    // 0.5 <= x < 1では縮約値u=1-xが0.5から0まで動くため、主近似の全中心を覆う。
    const Metrics full_reduced_range = scan_range(UINT32_C(0x3f000000),
                                                  UINT32_C(0x3f800000),
                                                  threads, false);
    merge_metrics(total, correction);
    merge_metrics(total, subnormal);
    merge_metrics(total, central);
    merge_metrics(total, full_reduced_range);

    std::printf(
        "checked=%llu correct=%llu violations=%llu max_ulp=%u monotonic=%llu\n",
        (unsigned long long)total.checked,
        (unsigned long long)total.correct,
        (unsigned long long)total.violations,
        total.max_ulp,
        (unsigned long long)total.monotonic);
    std::printf("worst=%08x first_failure=%08x\n",
                total.worst_input, total.first_failure);

    if (total.violations != 0 || total.monotonic != 0)
        return EXIT_FAILURE;
    return EXIT_SUCCESS;
}
