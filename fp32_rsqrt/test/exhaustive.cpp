// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0

#include <algorithm>
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

#include "VFP32Rsqrt.h"
#include "verilated.h"

namespace {

using uint128_t = unsigned __int128;

constexpr std::uint32_t kFractionCount = 1u << 23;
constexpr std::uint64_t kExpectedSignificands =
    2 * static_cast<std::uint64_t>(kFractionCount);

struct Options {
    int threads = 0;
};

struct Bounds {
    std::uint32_t lower = 0;
    std::uint32_t upper = 0;
    std::uint32_t rne = 0;
};

struct Failure {
    bool valid = false;
    std::uint32_t input = 0;
    std::uint32_t output = 0;
    std::uint32_t lower = 0;
    std::uint32_t upper = 0;
};

struct Stats {
    std::uint64_t significands = 0;
    std::uint64_t rtl_checks = 0;
    std::uint64_t faithful_failures = 0;
    std::uint64_t rne_matches = 0;
    std::uint64_t faithful_alternatives = 0;
    std::uint64_t maximum_rne_steps = 0;
    long double maximum_absolute_error_ulp = 0;
    std::uint64_t digest_xor = 0;
    std::uint64_t digest_sum = 0;
    Failure first_failure{};
};

std::uint64_t mix64(std::uint64_t value) {
    value += 0x9e3779b97f4a7c15ULL;
    value = (value ^ (value >> 30)) * 0xbf58476d1ce4e5b9ULL;
    value = (value ^ (value >> 27)) * 0x94d049bb133111ebULL;
    return value ^ (value >> 31);
}

std::uint32_t evaluate(VFP32Rsqrt& dut, std::uint32_t input) {
    dut.x = input;
    dut.eval();
    return dut.result;
}

uint128_t square_times_significand(
    std::uint32_t value, std::uint32_t significand) {
    return static_cast<uint128_t>(value) * value * significand;
}

std::uint32_t floor_output_significand(
    uint128_t numerator, std::uint32_t significand) {
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
    return low;
}

std::uint32_t pack_significand(
    std::uint32_t base_exponent, std::uint32_t significand) {
    if (significand == (1u << 24)) return (base_exponent + 1) << 23;
    return (base_exponent << 23) | (significand & 0x007fffffu);
}

Bounds positive_normal_bounds(std::uint32_t input) {
    const std::uint32_t exponent = (input >> 23) & 0xffu;
    const std::uint32_t fraction = input & 0x007fffffu;
    const std::uint32_t parity = (~exponent) & 1u;
    const std::uint32_t significand = 0x00800000u | fraction;
    const uint128_t numerator = static_cast<uint128_t>(1) << (71 - parity);
    const std::uint32_t base_exponent =
        (380u - exponent - (exponent & 1u)) >> 1;
    const std::uint32_t lower_sig =
        floor_output_significand(numerator, significand);
    const bool exact =
        square_times_significand(lower_sig, significand) == numerator;
    const std::uint32_t upper_sig = lower_sig + (!exact);
    std::uint32_t rne_sig = lower_sig;

    if (!exact) {
        const std::uint32_t twice_lower_plus_one = 2 * lower_sig + 1;
        const uint128_t midpoint_square =
            static_cast<uint128_t>(twice_lower_plus_one)
            * twice_lower_plus_one * significand;
        const uint128_t four_numerator = numerator << 2;
        if (midpoint_square < four_numerator
            || (midpoint_square == four_numerator && (lower_sig & 1u) != 0)) {
            ++rne_sig;
        }
    }
    return {
        pack_significand(base_exponent, lower_sig),
        pack_significand(base_exponent, upper_sig),
        pack_significand(base_exponent, rne_sig),
    };
}

std::uint32_t reference(std::uint32_t input) {
    const std::uint32_t sign = input >> 31;
    const std::uint32_t exponent = (input >> 23) & 0xffu;
    const std::uint32_t fraction = input & 0x007fffffu;
    if (exponent == 0xffu) {
        if (fraction != 0 || sign != 0) return 0x7fc00000u;
        return 0;
    }
    if (exponent == 0) return sign != 0 ? 0xff800000u : 0x7f800000u;
    if (sign != 0) return 0x7fc00000u;
    return positive_normal_bounds(input).rne;
}

std::uint64_t distance(std::uint32_t lhs, std::uint32_t rhs) {
    return lhs >= rhs
        ? static_cast<std::uint64_t>(lhs - rhs)
        : static_cast<std::uint64_t>(rhs - lhs);
}

void update_failure(
    Stats& stats,
    std::uint32_t input,
    std::uint32_t output,
    std::uint32_t lower,
    std::uint32_t upper) {
    if (!stats.first_failure.valid || input < stats.first_failure.input) {
        stats.first_failure = {true, input, output, lower, upper};
    }
}

void merge_stats(Stats& target, const Stats& source) {
    target.significands += source.significands;
    target.rtl_checks += source.rtl_checks;
    target.faithful_failures += source.faithful_failures;
    target.rne_matches += source.rne_matches;
    target.faithful_alternatives += source.faithful_alternatives;
    target.maximum_rne_steps = std::max(
        target.maximum_rne_steps, source.maximum_rne_steps);
    target.maximum_absolute_error_ulp = std::max(
        target.maximum_absolute_error_ulp,
        source.maximum_absolute_error_ulp);
    target.digest_xor ^= source.digest_xor;
    target.digest_sum += source.digest_sum;
    if (source.first_failure.valid) {
        update_failure(
            target,
            source.first_failure.input,
            source.first_failure.output,
            source.first_failure.lower,
            source.first_failure.upper);
    }
}

Options parse_options(int argc, char** argv) {
    Options options;
    for (int index = 1; index < argc; ++index) {
        const std::string_view argument = argv[index];
        if (argument.starts_with("--threads=")) {
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
            std::cerr << "usage: " << argv[0] << " [--threads=N]\n";
            std::exit(2);
        }
    }
    return options;
}

void check_representative_classes(VFP32Rsqrt& dut, Stats& stats) {
    constexpr std::uint32_t fractions[] = {
        0x000000u, 0x000001u, 0x03ffffu, 0x040000u,
        0x040001u, 0x3fffffu, 0x400000u, 0x7ffffeu, 0x7fffffu,
    };
    for (std::uint32_t sign : {0u, 0x80000000u}) {
        for (std::uint32_t exponent = 0; exponent <= 0xffu; ++exponent) {
            for (const std::uint32_t fraction : fractions) {
                const std::uint32_t input = sign | (exponent << 23) | fraction;
                const std::uint32_t output = evaluate(dut, input);
                ++stats.rtl_checks;
                std::uint32_t lower = reference(input);
                std::uint32_t upper = lower;
                if (sign == 0 && exponent != 0 && exponent != 0xffu) {
                    const Bounds bounds = positive_normal_bounds(input);
                    lower = bounds.lower;
                    upper = bounds.upper;
                }
                if (output != lower && output != upper) {
                    ++stats.faithful_failures;
                    update_failure(stats, input, output, lower, upper);
                }
            }
        }
    }
}

void report(int threads, const Stats& stats) {
    const bool pass = stats.significands == kExpectedSignificands
                   && stats.faithful_failures == 0
                   && stats.maximum_rne_steps <= 1;
    std::cout << "threads=" << threads << '\n'
              << "parity_significands=" << stats.significands << '\n'
              << "rtl_checks=" << stats.rtl_checks << '\n'
              << "rne_matches=" << stats.rne_matches << '\n'
              << "faithful_alternatives=" << stats.faithful_alternatives << '\n'
              << "faithful_failures=" << stats.faithful_failures << '\n'
              << "maximum_rne_steps=" << stats.maximum_rne_steps << '\n'
              << std::fixed << std::setprecision(12)
              << "maximum_absolute_error_ulp="
              << stats.maximum_absolute_error_ulp << '\n'
              << std::defaultfloat
              << "digest_xor=0x" << std::hex << std::setw(16)
              << std::setfill('0') << stats.digest_xor << '\n'
              << "digest_sum=0x" << std::setw(16) << stats.digest_sum << '\n'
              << std::dec << std::setfill(' ')
              << "first_failure_present="
              << (stats.first_failure.valid ? 1 : 0) << '\n';
    if (stats.first_failure.valid) {
        std::cout << "first_failure_input=0x" << std::hex << std::setw(8)
                  << std::setfill('0') << stats.first_failure.input << '\n'
                  << "first_failure_output=0x" << std::setw(8)
                  << stats.first_failure.output << '\n'
                  << "first_failure_lower=0x" << std::setw(8)
                  << stats.first_failure.lower << '\n'
                  << "first_failure_upper=0x" << std::setw(8)
                  << stats.first_failure.upper << '\n'
                  << std::dec << std::setfill(' ');
    }
    std::cout << "pass=" << (pass ? 1 : 0) << '\n';
    if (!pass) std::exit(1);
}

}  // namespace

int main(int argc, char** argv) {
    const Options options = parse_options(argc, argv);
    if (options.threads > 0) omp_set_num_threads(options.threads);
    omp_set_dynamic(0);
    const int thread_count = omp_get_max_threads();

    std::vector<std::unique_ptr<VerilatedContext>> contexts;
    std::vector<std::unique_ptr<VFP32Rsqrt>> models;
    std::vector<Stats> thread_stats(static_cast<std::size_t>(thread_count));
    contexts.reserve(static_cast<std::size_t>(thread_count));
    models.reserve(static_cast<std::size_t>(thread_count));
    for (int thread = 0; thread < thread_count; ++thread) {
        contexts.push_back(std::make_unique<VerilatedContext>());
        models.push_back(std::make_unique<VFP32Rsqrt>(contexts.back().get()));
    }

#pragma omp parallel
    {
        const int thread = omp_get_thread_num();
        VFP32Rsqrt& dut = *models[static_cast<std::size_t>(thread)];
        Stats& stats = thread_stats[static_cast<std::size_t>(thread)];

#pragma omp for schedule(static)
        for (std::uint64_t linear = 0; linear < kExpectedSignificands; ++linear) {
            const std::uint32_t parity = static_cast<std::uint32_t>(linear >> 23);
            const std::uint32_t fraction =
                static_cast<std::uint32_t>(linear) & 0x007fffffu;
            const std::uint32_t exponent = 127u + parity;
            const std::uint32_t input = (exponent << 23) | fraction;
            const std::uint32_t output = evaluate(dut, input);
            const Bounds bounds = positive_normal_bounds(input);

            ++stats.significands;
            ++stats.rtl_checks;
            if (output != bounds.lower && output != bounds.upper) {
                ++stats.faithful_failures;
                update_failure(stats, input, output, bounds.lower, bounds.upper);
            }
            const std::uint64_t rne_steps = distance(output, bounds.rne);
            stats.maximum_rne_steps = std::max(
                stats.maximum_rne_steps, rne_steps);
            if (rne_steps == 0) ++stats.rne_matches;
            else ++stats.faithful_alternatives;

            const std::uint32_t significand = 0x00800000u | fraction;
            const std::uint32_t base_exponent =
                (380u - exponent - (exponent & 1u)) >> 1;
            const std::uint32_t output_exponent = (output >> 23) & 0xffu;
            const std::uint32_t output_significand =
                0x00800000u | (output & 0x007fffffu);
            const long double output_coordinate = output_exponent == base_exponent
                ? static_cast<long double>(output_significand)
                : 2.0L * output_significand;
            const long double exact_coordinate = std::sqrt(
                std::ldexp(1.0L, 71 - static_cast<int>(parity))
                / static_cast<long double>(significand));
            stats.maximum_absolute_error_ulp = std::max(
                stats.maximum_absolute_error_ulp,
                std::fabs(output_coordinate - exact_coordinate));

            const std::uint64_t digest = mix64(
                (static_cast<std::uint64_t>(input) << 32) | output);
            stats.digest_xor ^= digest;
            stats.digest_sum += digest;
        }
    }

    Stats total;
    for (const Stats& stats : thread_stats) merge_stats(total, stats);
    check_representative_classes(*models.front(), total);
    report(thread_count, total);
    return 0;
}
