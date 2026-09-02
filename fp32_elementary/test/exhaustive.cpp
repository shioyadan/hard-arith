// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0

#include "VFP32Elementary.h"
#include "verilated.h"

#include <algorithm>
#include <bit>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <limits>
#include <memory>
#include <string_view>
#include <vector>

#include <omp.h>
#include <quadmath.h>

extern "C" std::uint32_t fp32_elementary_ref(
    std::uint32_t input, std::uint32_t op);
extern "C" double fp32_elementary_abs_error_units(
    std::uint32_t input, std::uint32_t op, std::uint32_t actual);

namespace {

using uint128_t = unsigned __int128;

constexpr std::uint32_t kFractionCount = 1u << 23;
constexpr std::uint32_t kCanonicalQnan = 0x7fc00000u;
constexpr std::uint32_t kPositiveInfinity = 0x7f800000u;
constexpr long double kAbsoluteLimit = 4.0L;

enum class Mode { all, reduced, exp2_active, exp2_full };

struct Options {
    Mode mode = Mode::all;
    int threads = 0;
};

struct Failure {
    bool valid = false;
    std::uint32_t input = 0;
    std::uint32_t output = 0;
    std::uint32_t reference = 0;
    std::uint32_t op = 0;
};

struct Metrics {
    std::uint64_t checks = 0;
    std::uint64_t exact = 0;
    std::uint64_t violations = 0;
    std::uint64_t monotonic_violations = 0;
    std::uint64_t max_monotonic_ulp = 0;
    std::uint64_t max_ulp = 0;
    long double max_abs_units = 0;
    std::uint32_t worst_input = 0;
    std::uint32_t worst_output = 0;
    std::uint32_t worst_reference = 0;
    std::uint32_t first_monotonic_input = 0;
    std::uint32_t first_monotonic_previous = 0;
    std::uint32_t first_monotonic_output = 0;
    Failure first_failure{};
};

struct Edge {
    bool valid = false;
    std::uint32_t first = 0;
    std::uint32_t last = 0;
    std::uint32_t first_input = 0;
};

struct ModelPool {
    std::vector<std::unique_ptr<VerilatedContext>> contexts;
    std::vector<std::unique_ptr<VFP32Elementary>> models;

    explicit ModelPool(int threads) {
        contexts.reserve(static_cast<std::size_t>(threads));
        models.reserve(static_cast<std::size_t>(threads));
        for (int thread = 0; thread < threads; ++thread) {
            contexts.push_back(std::make_unique<VerilatedContext>());
            models.push_back(std::make_unique<VFP32Elementary>(
                contexts.back().get()));
        }
    }

    ~ModelPool() {
        for (const auto& model : models) model->final();
    }
};

std::uint32_t ordered_key(std::uint32_t bits) {
    return (bits & 0x80000000u) != 0 ? ~bits : bits | 0x80000000u;
}

std::uint64_t ulp_distance(std::uint32_t lhs, std::uint32_t rhs) {
    const std::uint32_t lhs_key = ordered_key(lhs);
    const std::uint32_t rhs_key = ordered_key(rhs);
    return lhs_key >= rhs_key
        ? static_cast<std::uint64_t>(lhs_key - rhs_key)
        : static_cast<std::uint64_t>(rhs_key - lhs_key);
}

void update_monotonic(
    Metrics& metrics,
    std::uint32_t input,
    std::uint32_t previous,
    std::uint32_t output) {
    const std::uint64_t reversal = ulp_distance(previous, output);
    ++metrics.monotonic_violations;
    metrics.max_monotonic_ulp = std::max(
        metrics.max_monotonic_ulp, reversal);
    if (metrics.first_monotonic_input == 0
        || input < metrics.first_monotonic_input) {
        metrics.first_monotonic_input = input;
        metrics.first_monotonic_previous = previous;
        metrics.first_monotonic_output = output;
    }
}

std::uint32_t evaluate(
    VFP32Elementary& dut, std::uint32_t input, std::uint32_t op) {
    dut.x = input;
    dut.op = op;
    dut.eval();
    return dut.result;
}

bool is_finite(std::uint32_t bits) {
    return (bits & 0x7f800000u) != 0x7f800000u;
}

bool is_nan(std::uint32_t bits) {
    return (bits & 0x7fffffffu) > 0x7f800000u;
}

void update_failure(
    Metrics& metrics,
    std::uint32_t input,
    std::uint32_t output,
    std::uint32_t reference,
    std::uint32_t op) {
    if (!metrics.first_failure.valid
        || input < metrics.first_failure.input) {
        metrics.first_failure = {true, input, output, reference, op};
    }
}

void update_error(
    Metrics& metrics,
    std::uint32_t input,
    std::uint32_t output,
    std::uint32_t reference,
    std::uint64_t ulp,
    long double abs_units) {
    if (ulp > metrics.max_ulp) {
        metrics.max_ulp = ulp;
        metrics.worst_input = input;
        metrics.worst_output = output;
        metrics.worst_reference = reference;
    }
    metrics.max_abs_units = std::max(metrics.max_abs_units, abs_units);
}

void merge_metrics(Metrics& target, const Metrics& source) {
    target.checks += source.checks;
    target.exact += source.exact;
    target.violations += source.violations;
    target.monotonic_violations += source.monotonic_violations;
    target.max_monotonic_ulp = std::max(
        target.max_monotonic_ulp, source.max_monotonic_ulp);
    if (source.max_ulp > target.max_ulp) {
        target.max_ulp = source.max_ulp;
        target.worst_input = source.worst_input;
        target.worst_output = source.worst_output;
        target.worst_reference = source.worst_reference;
    }
    target.max_abs_units = std::max(
        target.max_abs_units, source.max_abs_units);
    if (source.first_failure.valid) {
        update_failure(
            target,
            source.first_failure.input,
            source.first_failure.output,
            source.first_failure.reference,
            source.first_failure.op);
    }
    if (source.first_monotonic_input != 0
        && (target.first_monotonic_input == 0
            || source.first_monotonic_input < target.first_monotonic_input)) {
        target.first_monotonic_input = source.first_monotonic_input;
        target.first_monotonic_previous = source.first_monotonic_previous;
        target.first_monotonic_output = source.first_monotonic_output;
    }
}

void report(std::string_view name, const Metrics& metrics, double seconds) {
    std::cout << "function=" << name << '\n'
              << "checks=" << metrics.checks << '\n'
              << "rne_matches=" << metrics.exact << '\n'
              << "violations=" << metrics.violations << '\n'
              << "max_ulp=" << metrics.max_ulp << '\n'
              << std::fixed << std::setprecision(12)
              << "max_abs_error=" << metrics.max_abs_units << "*2^-23\n"
              << "monotonic_violations="
              << metrics.monotonic_violations << '\n'
              << "max_monotonic_ulp=" << metrics.max_monotonic_ulp << '\n'
              << "elapsed_seconds=" << seconds << '\n'
              << std::defaultfloat
              << "worst_input=0x" << std::hex << std::setw(8)
              << std::setfill('0') << metrics.worst_input << '\n'
              << "worst_output=0x" << std::setw(8)
              << metrics.worst_output << '\n'
              << "worst_reference=0x" << std::setw(8)
              << metrics.worst_reference << '\n'
              << std::dec << std::setfill(' ')
              << "first_failure_present="
              << (metrics.first_failure.valid ? 1 : 0) << '\n';
    if (metrics.first_failure.valid) {
        std::cout << "first_failure_input=0x" << std::hex
                  << std::setw(8) << std::setfill('0')
                  << metrics.first_failure.input << '\n'
                  << "first_failure_output=0x" << std::setw(8)
                  << metrics.first_failure.output << '\n'
                  << "first_failure_reference=0x" << std::setw(8)
                  << metrics.first_failure.reference << '\n'
                  << std::dec << std::setfill(' ');
    }
    if (metrics.first_monotonic_input != 0) {
        std::cout << "first_monotonic_input=0x" << std::hex
                  << std::setw(8) << std::setfill('0')
                  << metrics.first_monotonic_input << '\n'
                  << "first_monotonic_previous=0x" << std::setw(8)
                  << metrics.first_monotonic_previous << '\n'
                  << "first_monotonic_output=0x" << std::setw(8)
                  << metrics.first_monotonic_output << '\n'
                  << std::dec << std::setfill(' ');
    }
}

Options parse_options(int argc, char** argv) {
    Options options;
    for (int index = 1; index < argc; ++index) {
        const std::string_view argument = argv[index];
        if (argument == "--all") {
            options.mode = Mode::all;
        } else if (argument == "--reduced-only") {
            options.mode = Mode::reduced;
        } else if (argument == "--exp2-active-only") {
            options.mode = Mode::exp2_active;
        } else if (argument == "--exp2-full-only") {
            options.mode = Mode::exp2_full;
        } else if (argument.starts_with("--threads=")) {
            const std::string_view number = argument.substr(10);
            char* end = nullptr;
            const long value = std::strtol(number.data(), &end, 10);
            if (end != number.data() + number.size()
                || value <= 0
                || value > std::numeric_limits<int>::max()) {
                std::cerr << "invalid thread count: " << number << '\n';
                std::exit(2);
            }
            options.threads = static_cast<int>(value);
        } else {
            std::cerr << "usage: " << argv[0]
                      << " [--all|--reduced-only|--exp2-active-only|"
                         "--exp2-full-only] [--threads=N]\n";
            std::exit(2);
        }
    }
    return options;
}

std::uint32_t rounded_reciprocal(std::uint32_t fraction) {
    if (fraction == 0) return 0x3f800000u;
    constexpr std::uint64_t numerator = std::uint64_t{1} << 47;
    const std::uint64_t denominator = 0x00800000u | fraction;
    std::uint64_t quotient = numerator / denominator;
    const std::uint64_t remainder = numerator % denominator;
    const std::uint64_t twice_remainder = remainder << 1;
    if (twice_remainder > denominator
        || (twice_remainder == denominator && (quotient & 1u) != 0)) {
        ++quotient;
    }
    return (126u << 23)
         | (static_cast<std::uint32_t>(quotient) & 0x007fffffu);
}

std::uint32_t integer_sqrt(std::uint64_t value) {
    std::uint64_t root = static_cast<std::uint64_t>(
        std::sqrt(static_cast<long double>(value)));
    while ((root + 1) * (root + 1) <= value) ++root;
    while (root * root > value) --root;
    return static_cast<std::uint32_t>(root);
}

std::uint32_t rounded_sqrt(std::uint32_t input) {
    const std::uint32_t exponent = (input >> 23) & 0xffu;
    const std::uint32_t fraction = input & 0x007fffffu;
    const std::uint32_t parity = (~exponent) & 1u;
    const std::uint32_t significand = 0x00800000u | fraction;
    const std::uint64_t radicand =
        static_cast<std::uint64_t>(significand) << (23 + parity);
    std::uint32_t root = integer_sqrt(radicand);
    const std::uint64_t remainder =
        radicand - static_cast<std::uint64_t>(root) * root;
    if (remainder > root) ++root;
    const std::uint32_t output_exponent =
        (exponent + 127u - parity) >> 1;
    if (root == (1u << 24)) return (output_exponent + 1) << 23;
    return (output_exponent << 23) | (root & 0x007fffffu);
}

uint128_t square_times_significand(
    std::uint32_t value, std::uint32_t significand) {
    return static_cast<uint128_t>(value) * value * significand;
}

std::uint32_t rounded_rsqrt(std::uint32_t input) {
    const std::uint32_t exponent = (input >> 23) & 0xffu;
    const std::uint32_t fraction = input & 0x007fffffu;
    const std::uint32_t parity = (~exponent) & 1u;
    const std::uint32_t significand = 0x00800000u | fraction;
    const uint128_t numerator = static_cast<uint128_t>(1) << (71 - parity);
    std::uint32_t low = 1u << 23;
    std::uint32_t high = 1u << 24;
    while (low < high) {
        const std::uint32_t middle = low + (high - low + 1) / 2;
        if (square_times_significand(middle, significand) <= numerator) {
            low = middle;
        } else {
            high = middle - 1;
        }
    }
    const bool exact =
        square_times_significand(low, significand) == numerator;
    std::uint32_t rounded = low;
    if (!exact) {
        const std::uint32_t twice_lower_plus_one = 2 * low + 1;
        const uint128_t midpoint_square =
            static_cast<uint128_t>(twice_lower_plus_one)
            * twice_lower_plus_one * significand;
        const uint128_t four_numerator = numerator << 2;
        if (midpoint_square < four_numerator
            || (midpoint_square == four_numerator && (low & 1u) != 0)) {
            ++rounded;
        }
    }
    const std::uint32_t output_exponent =
        (380u - exponent - (exponent & 1u)) >> 1;
    if (rounded == (1u << 24)) return (output_exponent + 1) << 23;
    return (output_exponent << 23) | (rounded & 0x007fffffu);
}

void merge_decreasing_edges(Metrics& metrics, const std::vector<Edge>& edges) {
    for (std::size_t index = 1; index < edges.size(); ++index) {
        if (edges[index - 1].valid && edges[index].valid
            && ordered_key(edges[index].first)
                > ordered_key(edges[index - 1].last)) {
            update_monotonic(
                metrics, edges[index].first_input,
                edges[index - 1].last, edges[index].first);
        }
    }
}

void merge_increasing_edges(Metrics& metrics, const std::vector<Edge>& edges) {
    for (std::size_t index = 1; index < edges.size(); ++index) {
        if (edges[index - 1].valid && edges[index].valid
            && ordered_key(edges[index].first)
                < ordered_key(edges[index - 1].last)) {
            update_monotonic(
                metrics, edges[index].first_input,
                edges[index - 1].last, edges[index].first);
        }
    }
}

Metrics run_reciprocal(ModelPool& pool, int threads) {
    std::vector<Metrics> locals(static_cast<std::size_t>(threads));
    std::vector<Edge> edges(static_cast<std::size_t>(threads));
#pragma omp parallel num_threads(threads)
    {
        const int thread = omp_get_thread_num();
        Verilated::threadContextp(pool.contexts[thread].get());
        VFP32Elementary& dut = *pool.models[thread];
        Metrics& metrics = locals[thread];
        std::uint32_t previous = 0;
        bool have_previous = false;
#pragma omp for schedule(static)
        for (std::uint64_t linear = 0; linear < kFractionCount; ++linear) {
            const std::uint32_t fraction = static_cast<std::uint32_t>(linear);
            const std::uint32_t input = (127u << 23) | fraction;
            const std::uint32_t reference = rounded_reciprocal(fraction);
            const std::uint32_t output = evaluate(dut, input, 0x02u);
            const std::uint32_t negative_output = evaluate(
                dut, input | 0x80000000u, 0x02u);
            const std::uint64_t distance = ulp_distance(output, reference);
            const std::uint64_t negative_distance = ulp_distance(
                negative_output, reference | 0x80000000u);
            metrics.checks += 2;
            metrics.exact += (distance == 0) + (negative_distance == 0);
            if (distance > 1) {
                ++metrics.violations;
                update_failure(metrics, input, output, reference, 0x02u);
            }
            if (negative_distance > 1
                || negative_output != (output | 0x80000000u)) {
                ++metrics.violations;
                update_failure(
                    metrics,
                    input | 0x80000000u,
                    negative_output,
                    reference | 0x80000000u,
                    0x02u);
            }
            update_error(
                metrics, input, output, reference,
                std::max(distance, negative_distance), 0);
            if (!have_previous) {
                edges[thread].valid = true;
                edges[thread].first = output;
                edges[thread].first_input = input;
                have_previous = true;
            } else if (ordered_key(output) > ordered_key(previous)) {
                update_monotonic(metrics, input, previous, output);
            }
            previous = output;
            edges[thread].last = output;
        }
    }
    Metrics total;
    for (const Metrics& metrics : locals) merge_metrics(total, metrics);
    merge_decreasing_edges(total, edges);
    return total;
}

Metrics run_sqrt_like(ModelPool& pool, int threads, bool reciprocal) {
    constexpr std::uint64_t count = 2ull * kFractionCount;
    const std::uint32_t op = reciprocal ? 0x04u : 0x08u;
    std::vector<Metrics> locals(static_cast<std::size_t>(threads));
    std::vector<Edge> edges(static_cast<std::size_t>(threads));
#pragma omp parallel num_threads(threads)
    {
        const int thread = omp_get_thread_num();
        Verilated::threadContextp(pool.contexts[thread].get());
        VFP32Elementary& dut = *pool.models[thread];
        Metrics& metrics = locals[thread];
        std::uint32_t previous = 0;
        bool have_previous = false;
#pragma omp for schedule(static)
        for (std::uint64_t linear = 0; linear < count; ++linear) {
            const std::uint32_t parity = static_cast<std::uint32_t>(linear >> 23);
            const std::uint32_t fraction =
                static_cast<std::uint32_t>(linear) & 0x007fffffu;
            const std::uint32_t input = ((127u + parity) << 23) | fraction;
            const std::uint32_t reference = reciprocal
                ? rounded_rsqrt(input) : rounded_sqrt(input);
            const std::uint32_t output = evaluate(dut, input, op);
            const std::uint64_t distance = ulp_distance(output, reference);
            ++metrics.checks;
            metrics.exact += distance == 0;
            if (distance > 1) {
                ++metrics.violations;
                update_failure(metrics, input, output, reference, op);
            }
            update_error(metrics, input, output, reference, distance, 0);
            if (!have_previous) {
                edges[thread].valid = true;
                edges[thread].first = output;
                edges[thread].first_input = input;
                have_previous = true;
            } else {
                const bool violation = reciprocal
                    ? ordered_key(output) > ordered_key(previous)
                    : ordered_key(output) < ordered_key(previous);
                if (violation) {
                    update_monotonic(metrics, input, previous, output);
                }
            }
            previous = output;
            edges[thread].last = output;
        }
    }
    Metrics total;
    for (const Metrics& metrics : locals) merge_metrics(total, metrics);
    if (reciprocal) merge_decreasing_edges(total, edges);
    else merge_increasing_edges(total, edges);
    return total;
}

Metrics run_log2(ModelPool& pool, int threads) {
    constexpr std::uint64_t count = 2ull * kFractionCount;
    std::vector<Metrics> locals(static_cast<std::size_t>(threads));
    std::vector<Edge> edges(static_cast<std::size_t>(threads));
#pragma omp parallel num_threads(threads)
    {
        const int thread = omp_get_thread_num();
        Verilated::threadContextp(pool.contexts[thread].get());
        VFP32Elementary& dut = *pool.models[thread];
        Metrics& metrics = locals[thread];
        std::uint32_t previous = 0;
        bool have_previous = false;
#pragma omp for schedule(static)
        for (std::uint64_t linear = 0; linear < count; ++linear) {
            const std::uint32_t exponent = 126u
                + static_cast<std::uint32_t>(linear >> 23);
            const std::uint32_t fraction =
                static_cast<std::uint32_t>(linear) & 0x007fffffu;
            const std::uint32_t input = (exponent << 23) | fraction;
            const float input_value = std::bit_cast<float>(input);
            const __float128 exact = log2q(static_cast<__float128>(input_value));
            const std::uint32_t reference = std::bit_cast<std::uint32_t>(
                static_cast<float>(exact));
            const std::uint32_t output = evaluate(dut, input, 0x10u);
            const std::uint64_t distance = ulp_distance(output, reference);
            const long double abs_units = static_cast<long double>(
                fabsq(static_cast<__float128>(std::bit_cast<float>(output))
                    - exact) * 8388608.0Q);
            ++metrics.checks;
            metrics.exact += distance == 0;
            if (distance > 2 && abs_units > kAbsoluteLimit) {
                ++metrics.violations;
                update_failure(metrics, input, output, reference, 0x10u);
            }
            update_error(
                metrics, input, output, reference, distance, abs_units);
            if (!have_previous) {
                edges[thread].valid = true;
                edges[thread].first = output;
                edges[thread].first_input = input;
                have_previous = true;
            } else if (ordered_key(output) < ordered_key(previous)) {
                update_monotonic(metrics, input, previous, output);
            }
            previous = output;
            edges[thread].last = output;
        }
    }
    Metrics total;
    for (const Metrics& metrics : locals) merge_metrics(total, metrics);
    merge_increasing_edges(total, edges);
    return total;
}

Metrics run_sine_or_cosine(ModelPool& pool, int threads, bool cosine) {
    constexpr std::uint32_t begin = 0x3f000000u;
    constexpr std::uint64_t count = (1ull << 22) + 1;
    const std::uint32_t op = cosine ? 0x40u : 0x20u;
    const long double pi = acosl(-1.0L);
    const long double half_phase_lsb = ldexpl(1.0L, -24);
    std::vector<Metrics> locals(static_cast<std::size_t>(threads));
    std::vector<Edge> edges(static_cast<std::size_t>(threads));
#pragma omp parallel num_threads(threads)
    {
        const int thread = omp_get_thread_num();
        Verilated::threadContextp(pool.contexts[thread].get());
        VFP32Elementary& dut = *pool.models[thread];
        Metrics& metrics = locals[thread];
        std::uint32_t previous = 0;
        bool have_previous = false;
#pragma omp for schedule(static)
        for (std::uint64_t linear = 0; linear < count; ++linear) {
            const std::uint32_t input = begin
                + 2 * static_cast<std::uint32_t>(linear);
            const long double x = static_cast<long double>(
                std::bit_cast<float>(input));
            const long double reduced = cosine ? x - 0.5L : 1.0L - x;
            const long double reduced_low =
                std::max(0.0L, reduced - half_phase_lsb);
            const long double reduced_high =
                std::min(0.5L, reduced + half_phase_lsb);
            const long double error_low_reference = sinl(pi * reduced_low);
            const long double error_high_reference = sinl(pi * reduced_high);
            const std::uint32_t output = evaluate(dut, input, op);
            const long double actual = fabsl(static_cast<long double>(
                std::bit_cast<float>(output)));
            const long double error_low =
                fabsl(actual - error_low_reference) * 8388608.0L;
            const long double error_high =
                fabsl(actual - error_high_reference) * 8388608.0L;
            const long double abs_units = std::max(error_low, error_high);
            const std::uint32_t reference_magnitude =
                std::bit_cast<std::uint32_t>(static_cast<float>(
                    sinl(pi * reduced)));
            const std::uint32_t reference = cosine && reduced != 0
                ? reference_magnitude | 0x80000000u : reference_magnitude;
            const std::uint64_t distance = ulp_distance(output, reference);
            ++metrics.checks;
            metrics.exact += distance == 0;
            if (!is_finite(output) || abs_units > kAbsoluteLimit + 1.0e-6L) {
                ++metrics.violations;
                update_failure(metrics, input, output, reference, op);
            }
            update_error(
                metrics, input, output, reference, distance, abs_units);
            if (!have_previous) {
                edges[thread].valid = true;
                edges[thread].first = output;
                edges[thread].first_input = input;
                have_previous = true;
            } else if (ordered_key(output) > ordered_key(previous)) {
                update_monotonic(metrics, input, previous, output);
            }
            previous = output;
            edges[thread].last = output;
        }
    }
    Metrics total;
    for (const Metrics& metrics : locals) merge_metrics(total, metrics);
    merge_decreasing_edges(total, edges);
    return total;
}

bool contract_accepts(
    std::uint32_t input,
    std::uint32_t op,
    std::uint32_t output,
    std::uint32_t reference,
    std::uint64_t& distance,
    long double& abs_units) {
    if (is_nan(reference)) return output == kCanonicalQnan;
    if (!is_finite(reference)) return output == reference;
    if (!is_finite(output)) return false;
    distance = ulp_distance(output, reference);
    if (op == 0x10u || op == 0x20u || op == 0x40u) {
        abs_units = static_cast<long double>(
            fp32_elementary_abs_error_units(input, op, output));
    }
    if (op == 0x10u) return distance <= 2 || abs_units <= kAbsoluteLimit;
    if (op == 0x20u || op == 0x40u) return abs_units <= kAbsoluteLimit;
    return distance <= 1;
}

std::vector<std::uint32_t> boundary_fractions() {
    std::vector<std::uint32_t> fractions = {
        0u, 1u, 2u, 0x003fffffu, 0x00400000u,
        0x00400001u, 0x007ffffdu, 0x007ffffeu, 0x007fffffu,
    };
    for (std::uint32_t shift : {16u, 17u}) {
        const std::uint32_t count = 1u << (23 - shift);
        for (std::uint32_t index = 0; index < count; ++index) {
            const std::uint32_t boundary = index << shift;
            for (int delta = -2; delta <= 2; ++delta) {
                const std::int64_t candidate =
                    static_cast<std::int64_t>(boundary) + delta;
                if (candidate >= 0 && candidate < kFractionCount) {
                    fractions.push_back(static_cast<std::uint32_t>(candidate));
                }
            }
        }
    }
    std::sort(fractions.begin(), fractions.end());
    fractions.erase(std::unique(fractions.begin(), fractions.end()),
                    fractions.end());
    return fractions;
}

std::vector<Metrics> run_all_exponent_boundaries(
    ModelPool& pool, int threads) {
    constexpr std::uint32_t operations[] = {
        0x01u, 0x02u, 0x04u, 0x08u, 0x10u, 0x20u, 0x40u,
    };
    const std::vector<std::uint32_t> fractions = boundary_fractions();
    const std::uint64_t inputs =
        2ull * 256ull * static_cast<std::uint64_t>(fractions.size());
    const std::uint64_t count = inputs * std::size(operations);
    std::vector<std::vector<Metrics>> locals(
        static_cast<std::size_t>(threads),
        std::vector<Metrics>(std::size(operations)));
#pragma omp parallel num_threads(threads)
    {
        const int thread = omp_get_thread_num();
        Verilated::threadContextp(pool.contexts[thread].get());
        VFP32Elementary& dut = *pool.models[thread];
#pragma omp for schedule(static)
        for (std::uint64_t linear = 0; linear < count; ++linear) {
            const std::size_t function = static_cast<std::size_t>(
                linear % std::size(operations));
            std::uint64_t input_index = linear / std::size(operations);
            const std::uint32_t fraction = fractions[
                static_cast<std::size_t>(input_index % fractions.size())];
            input_index /= fractions.size();
            const std::uint32_t exponent =
                static_cast<std::uint32_t>(input_index % 256u);
            const std::uint32_t sign =
                static_cast<std::uint32_t>(input_index / 256u) << 31;
            const std::uint32_t input = sign | (exponent << 23) | fraction;
            const std::uint32_t op = operations[function];
            const std::uint32_t reference = fp32_elementary_ref(input, op);
            const std::uint32_t output = evaluate(dut, input, op);
            std::uint64_t distance = 0;
            long double abs_units = 0;
            Metrics& metrics = locals[thread][function];
            ++metrics.checks;
            const bool accepted = contract_accepts(
                input, op, output, reference, distance, abs_units);
            metrics.exact += output == reference;
            if (!accepted) {
                ++metrics.violations;
                update_failure(metrics, input, output, reference, op);
            }
            update_error(
                metrics, input, output, reference, distance, abs_units);
        }
    }
    std::vector<Metrics> totals(std::size(operations));
    for (const auto& per_thread : locals) {
        for (std::size_t function = 0; function < totals.size(); ++function) {
            merge_metrics(totals[function], per_thread[function]);
        }
    }
    std::cout << "boundary_fraction_patterns=" << fractions.size() << '\n'
              << "boundary_inputs_per_function=" << inputs << '\n';
    return totals;
}

std::uint64_t run_invalid_operations(ModelPool& pool) {
    constexpr std::uint32_t inputs[] = {
        0x00000000u, 0x80000000u, 0x00000001u, 0x007fffffu,
        0x00800000u, 0x3effffffu, 0x3f000000u, 0x3f7fffffu,
        0x3f800000u, 0x40000000u, 0x7f7fffffu, 0xff7fffffu,
        0x7f800000u, 0xff800000u, 0x7fc00001u, 0xffc12345u,
    };
    VFP32Elementary& dut = *pool.models.front();
    std::uint64_t failures = 0;
    std::uint64_t checks = 0;
    for (std::uint32_t op = 0; op < 128; ++op) {
        if (op != 0 && (op & (op - 1)) == 0) continue;
        for (const std::uint32_t input : inputs) {
            ++checks;
            failures += evaluate(dut, input, op) != kCanonicalQnan;
        }
    }
    std::cout << "invalid_op_checks=" << checks << '\n'
              << "invalid_op_failures=" << failures << '\n';
    return failures;
}

std::uint32_t ftz_exp2_reference_from_double(double exact) {
    if (std::isinf(exact)) return kPositiveInfinity;
    const std::uint32_t bits = std::bit_cast<std::uint32_t>(
        static_cast<float>(exact));
    return (bits & 0x7f800000u) == 0 ? 0u : bits;
}

std::uint32_t ftz_exp2_reference_from_quad(float input) {
    const __float128 exact = exp2q(static_cast<__float128>(input));
    if (isinfq(exact)) return kPositiveInfinity;
    const std::uint32_t bits = std::bit_cast<std::uint32_t>(
        static_cast<float>(exact));
    return (bits & 0x7f800000u) == 0 ? 0u : bits;
}

std::uint32_t exp2_input(bool full, std::uint64_t index) {
    if (full) return static_cast<std::uint32_t>(index);
    constexpr std::uint32_t exponent_count = 33;
    const std::uint32_t slot = static_cast<std::uint32_t>(index >> 23);
    const std::uint32_t fraction = static_cast<std::uint32_t>(index)
                                 & 0x007fffffu;
    return ((slot / exponent_count) << 31)
         | ((102u + slot % exponent_count) << 23)
         | fraction;
}

struct Exp2Metrics : Metrics {
    std::uint64_t special_checks = 0;
    std::uint64_t special_mismatches = 0;
    std::uint64_t binary128_candidates = 0;
    std::uint64_t binary128_reference_corrections = 0;
    std::uint64_t positive_violations = 0;
    std::uint64_t negative_violations = 0;
    std::uint32_t first_correction_input = 0;
    std::uint32_t first_double_reference = 0;
    std::uint32_t first_binary128_reference = 0;
    std::uint64_t digest_xor = 0;
    std::uint64_t digest_sum = 0;
};

std::uint64_t mix64(std::uint64_t value) {
    value += 0x9e3779b97f4a7c15ULL;
    value = (value ^ (value >> 30)) * 0xbf58476d1ce4e5b9ULL;
    value = (value ^ (value >> 27)) * 0x94d049bb133111ebULL;
    return value ^ (value >> 31);
}

void merge_exp2(Exp2Metrics& target, const Exp2Metrics& source) {
    merge_metrics(target, source);
    target.special_checks += source.special_checks;
    target.special_mismatches += source.special_mismatches;
    target.binary128_candidates += source.binary128_candidates;
    target.binary128_reference_corrections +=
        source.binary128_reference_corrections;
    target.positive_violations += source.positive_violations;
    target.negative_violations += source.negative_violations;
    if (source.first_correction_input != 0
        && (target.first_correction_input == 0
            || source.first_correction_input < target.first_correction_input)) {
        target.first_correction_input = source.first_correction_input;
        target.first_double_reference = source.first_double_reference;
        target.first_binary128_reference = source.first_binary128_reference;
    }
    target.digest_xor ^= source.digest_xor;
    target.digest_sum += source.digest_sum;
}

Exp2Metrics run_exp2(ModelPool& pool, int threads, bool full) {
    const std::uint64_t count = full
        ? (1ull << 32) : 2ull * 33ull * kFractionCount;
    std::vector<Exp2Metrics> locals(static_cast<std::size_t>(threads));
    std::vector<Edge> positive_edges(static_cast<std::size_t>(threads));
    std::vector<Edge> negative_edges(static_cast<std::size_t>(threads));
#pragma omp parallel num_threads(threads)
    {
        const int thread = omp_get_thread_num();
        Verilated::threadContextp(pool.contexts[thread].get());
        VFP32Elementary& dut = *pool.models[thread];
        Exp2Metrics& metrics = locals[thread];
        std::uint32_t previous_input = 0;
        std::uint32_t previous_output = 0;
        bool have_previous = false;
#pragma omp for schedule(static)
        for (std::uint64_t index = 0; index < count; ++index) {
            const std::uint32_t input = exp2_input(full, index);
            const std::uint32_t output = evaluate(dut, input, 0x01u);
            const std::uint32_t exponent = (input >> 23) & 0xffu;
            const std::uint32_t fraction = input & 0x007fffffu;
            std::uint32_t reference = 0;
            const bool special = exponent == 0xffu;
            if (special) {
                reference = fraction != 0 ? kCanonicalQnan
                    : ((input >> 31) != 0 ? 0u : kPositiveInfinity);
                ++metrics.special_checks;
                if (output != reference) {
                    ++metrics.special_mismatches;
                    ++metrics.violations;
                    update_failure(metrics, input, output, reference, 0x01u);
                }
            } else {
                const float input_value = std::bit_cast<float>(input);
                const double exact = std::exp2(static_cast<double>(input_value));
                reference = ftz_exp2_reference_from_double(exact);
                std::uint64_t distance = ulp_distance(output, reference);
                bool near_boundary = false;
                const bool endpoint_boundary =
                    (input_value >= -127.0f && input_value <= -125.0f)
                    || (input_value >= 127.0f && input_value <= 129.0f);
                if (exact > 0.0 && std::isfinite(exact)
                    && reference != 0 && reference != kPositiveInfinity) {
                    const float rounded = std::bit_cast<float>(reference);
                    const double ulp = std::ldexp(
                        1.0, std::ilogb(exact) - 23);
                    const double grid_distance =
                        std::abs(exact - static_cast<double>(rounded)) / ulp;
                    near_boundary =
                        std::abs(grid_distance - 0.5) <= 0x1p-20;
                }
                if (endpoint_boundary || near_boundary || distance > 1) {
                    ++metrics.binary128_candidates;
                    const std::uint32_t audited =
                        ftz_exp2_reference_from_quad(input_value);
                    if (audited != reference) {
                        ++metrics.binary128_reference_corrections;
                        if (metrics.first_correction_input == 0
                            || input < metrics.first_correction_input) {
                            metrics.first_correction_input = input;
                            metrics.first_double_reference = reference;
                            metrics.first_binary128_reference = audited;
                        }
                    }
                    reference = audited;
                    distance = ulp_distance(output, reference);
                }
                ++metrics.checks;
                metrics.exact += distance == 0;
                if (distance > 1) {
                    ++metrics.violations;
                    if ((input >> 31) == 0) ++metrics.positive_violations;
                    else ++metrics.negative_violations;
                    update_failure(metrics, input, output, reference, 0x01u);
                }
                update_error(metrics, input, output, reference, distance, 0);
            }
            const std::uint64_t digest = mix64(
                (static_cast<std::uint64_t>(input) << 32) | output);
            metrics.digest_xor ^= digest;
            metrics.digest_sum += digest;

            if (full && !special) {
                Edge& edge = (input >> 31) == 0
                    ? positive_edges[thread] : negative_edges[thread];
                if (!edge.valid) {
                    edge.valid = true;
                    edge.first = output;
                    edge.first_input = input;
                }
                edge.last = output;
                if (have_previous
                    && (previous_input >> 31) == (input >> 31)
                    && ((input >> 23) & 0xffu) != 0xffu) {
                    const bool violation = (input >> 31) == 0
                        ? ordered_key(output) < ordered_key(previous_output)
                        : ordered_key(output) > ordered_key(previous_output);
                    if (violation) {
                        update_monotonic(
                            metrics, input, previous_output, output);
                    }
                }
                previous_input = input;
                previous_output = output;
                have_previous = true;
            }
        }
    }
    Exp2Metrics total;
    for (const Exp2Metrics& metrics : locals) merge_exp2(total, metrics);
    if (full) {
        merge_increasing_edges(total, positive_edges);
        merge_decreasing_edges(total, negative_edges);
    }
    return total;
}

template <typename Function>
Metrics timed_run(
    std::string_view name, Function&& function, bool& pass,
    bool monotonic_required = true) {
    const auto begin = std::chrono::steady_clock::now();
    Metrics metrics = function();
    const double seconds = std::chrono::duration<double>(
        std::chrono::steady_clock::now() - begin).count();
    report(name, metrics, seconds);
    pass &= metrics.violations == 0
         && (!monotonic_required || metrics.monotonic_violations == 0);
    return metrics;
}

}  // namespace

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    const Options options = parse_options(argc, argv);
    if (options.threads > 0) omp_set_num_threads(options.threads);
    omp_set_dynamic(0);
    const int threads = omp_get_max_threads();
    ModelPool pool(threads);
    bool pass = true;

    std::cout << "threads=" << threads << '\n'
              << "oracle=integer-exact reciprocal/sqrt/rsqrt; "
                 "binary128 log2/boundaries; long-double reduced phase; "
                 "binary64 exp2 with binary128 boundary audit\n";

    if (options.mode == Mode::all || options.mode == Mode::reduced) {
        timed_run("recip", [&] { return run_reciprocal(pool, threads); }, pass);
        timed_run("rsqrt", [&] {
            return run_sqrt_like(pool, threads, true);
        }, pass);
        timed_run("sqrt", [&] {
            return run_sqrt_like(pool, threads, false);
        }, pass);
        timed_run("log2", [&] { return run_log2(pool, threads); }, pass);
        timed_run("sinpi", [&] {
            return run_sine_or_cosine(pool, threads, false);
        }, pass, false);
        timed_run("cospi", [&] {
            return run_sine_or_cosine(pool, threads, true);
        }, pass, false);

        const auto boundary_begin = std::chrono::steady_clock::now();
        const std::vector<Metrics> boundary =
            run_all_exponent_boundaries(pool, threads);
        constexpr std::string_view names[] = {
            "exp2-boundary", "recip-boundary", "rsqrt-boundary",
            "sqrt-boundary", "log2-boundary", "sinpi-boundary",
            "cospi-boundary",
        };
        const double seconds = std::chrono::duration<double>(
            std::chrono::steady_clock::now() - boundary_begin).count();
        for (std::size_t index = 0; index < boundary.size(); ++index) {
            report(names[index], boundary[index], seconds);
            pass &= boundary[index].violations == 0;
        }
        pass &= run_invalid_operations(pool) == 0;
    }

    if (options.mode == Mode::all
        || options.mode == Mode::exp2_active
        || options.mode == Mode::exp2_full) {
        const bool full = options.mode != Mode::exp2_active;
        const auto begin = std::chrono::steady_clock::now();
        const Exp2Metrics metrics = run_exp2(pool, threads, full);
        const double seconds = std::chrono::duration<double>(
            std::chrono::steady_clock::now() - begin).count();
        report(full ? "exp2-full" : "exp2-active", metrics, seconds);
        std::cout << "exp2_special_checks=" << metrics.special_checks << '\n'
                  << "exp2_special_mismatches="
                  << metrics.special_mismatches << '\n'
                  << "exp2_binary128_candidates="
                  << metrics.binary128_candidates << '\n'
                  << "exp2_binary128_reference_corrections="
                  << metrics.binary128_reference_corrections << '\n'
                  << "exp2_positive_violations="
                  << metrics.positive_violations << '\n'
                  << "exp2_negative_violations="
                  << metrics.negative_violations << '\n'
                  << "exp2_digest_xor=0x" << std::hex << std::setw(16)
                  << std::setfill('0') << metrics.digest_xor << '\n'
                  << "exp2_digest_sum=0x" << std::setw(16)
                  << metrics.digest_sum << '\n'
                  << std::dec << std::setfill(' ');
        if (metrics.first_correction_input != 0) {
            std::cout << "exp2_first_correction_input=0x" << std::hex
                      << std::setw(8) << std::setfill('0')
                      << metrics.first_correction_input << '\n'
                      << "exp2_first_double_reference=0x" << std::setw(8)
                      << metrics.first_double_reference << '\n'
                      << "exp2_first_binary128_reference=0x" << std::setw(8)
                      << metrics.first_binary128_reference << '\n'
                      << std::dec << std::setfill(' ');
        }
        pass &= metrics.violations == 0
             && metrics.special_mismatches == 0
             && (!full || metrics.monotonic_violations == 0);
    }

    std::cout << "pass=" << (pass ? 1 : 0) << '\n';
    return pass ? 0 : 1;
}
