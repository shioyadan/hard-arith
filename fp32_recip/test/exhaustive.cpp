// Copyright 2026 Ryota Shioya
// SPDX-License-Identifier: Apache-2.0

#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <limits>
#include <memory>
#include <string_view>
#include <vector>

#include <omp.h>

#include "VFP32Recip.h"
#include "verilated.h"

namespace {

constexpr std::uint32_t kFractionCount = 1u << 23;
constexpr std::uint64_t kNumerator = std::uint64_t{1} << 47;

struct Options {
    int threads = 0;
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
    std::uint64_t sign_symmetry_failures = 0;
    std::uint64_t rne_matches = 0;
    std::uint64_t faithful_alternatives = 0;
    std::uint64_t maximum_rne_steps = 0;
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

std::uint32_t evaluate(VFP32Recip& dut, std::uint32_t input) {
    dut.x = input;
    dut.eval();
    return dut.result;
}

std::uint32_t ordered_key(std::uint32_t bits) {
    return (bits & 0x80000000u) != 0 ? ~bits : bits | 0x80000000u;
}

std::uint64_t distance(std::uint32_t lhs, std::uint32_t rhs) {
    const std::uint32_t lhs_key = ordered_key(lhs);
    const std::uint32_t rhs_key = ordered_key(rhs);
    return lhs_key >= rhs_key
        ? static_cast<std::uint64_t>(lhs_key - rhs_key)
        : static_cast<std::uint64_t>(rhs_key - lhs_key);
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
    target.sign_symmetry_failures += source.sign_symmetry_failures;
    target.rne_matches += source.rne_matches;
    target.faithful_alternatives += source.faithful_alternatives;
    target.maximum_rne_steps = std::max(
        target.maximum_rne_steps, source.maximum_rne_steps);
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

std::uint32_t rne_significand(
    std::uint64_t lower,
    std::uint64_t remainder,
    std::uint64_t denominator) {
    const std::uint64_t twice_remainder = remainder << 1;
    if (twice_remainder > denominator
        || (twice_remainder == denominator && (lower & 1u) != 0)) {
        ++lower;
    }
    return static_cast<std::uint32_t>(lower);
}

std::uint32_t reference(std::uint32_t input) {
    const std::uint32_t sign = input & 0x80000000u;
    const std::uint32_t exponent = (input >> 23) & 0xffu;
    const std::uint32_t fraction = input & 0x007fffffu;
    if (exponent == 0xffu) {
        if (fraction != 0) return 0x7fc00000u;
        return sign;
    }
    if (exponent == 0) return sign | 0x7f800000u;
    if (exponent == 0xfeu || (exponent == 0xfdu && fraction != 0)) {
        return sign;
    }
    if (fraction == 0) return sign | ((254u - exponent) << 23);

    const std::uint64_t denominator = 0x00800000u | fraction;
    const std::uint64_t lower = kNumerator / denominator;
    const std::uint64_t remainder = kNumerator % denominator;
    const std::uint32_t rounded =
        rne_significand(lower, remainder, denominator);
    return sign | ((253u - exponent) << 23)
         | (rounded & 0x007fffffu);
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

void check_representative_classes(VFP32Recip& dut, Stats& stats) {
    constexpr std::uint32_t fractions[] = {
        0x000000u, 0x000001u, 0x03ffffu, 0x040000u,
        0x040001u, 0x3fffffu, 0x400000u, 0x7ffffeu, 0x7fffffu,
    };

    for (std::uint32_t sign : {0u, 0x80000000u}) {
        for (std::uint32_t exponent = 0; exponent <= 0xffu; ++exponent) {
            for (const std::uint32_t fraction : fractions) {
                const std::uint32_t input = sign | (exponent << 23) | fraction;
                const std::uint32_t expected = reference(input);
                const std::uint32_t output = evaluate(dut, input);
                ++stats.rtl_checks;
                const bool both_nan = (expected & 0x7fffffffu) > 0x7f800000u
                                   && (output & 0x7fffffffu) > 0x7f800000u;
                const bool result_is_unique = exponent == 0
                                           || exponent == 0xffu
                                           || exponent == 0xfeu
                                           || (exponent == 0xfdu && fraction != 0)
                                           || fraction == 0;
                bool faithful = output == expected || both_nan;
                std::uint32_t lower = expected;
                std::uint32_t upper = expected;
                if (!result_is_unique) {
                    const std::uint64_t denominator = 0x00800000u | fraction;
                    const std::uint64_t lower_sig = kNumerator / denominator;
                    const std::uint64_t remainder = kNumerator % denominator;
                    const std::uint64_t upper_sig = lower_sig + (remainder != 0);
                    const std::uint32_t result_exponent = 253u - exponent;
                    const std::uint32_t lower_magnitude =
                        (result_exponent << 23)
                        | (static_cast<std::uint32_t>(lower_sig) & 0x007fffffu);
                    const std::uint32_t upper_magnitude =
                        (result_exponent << 23)
                        | (static_cast<std::uint32_t>(upper_sig) & 0x007fffffu);
                    lower = sign == 0 ? lower_magnitude : sign | upper_magnitude;
                    upper = sign == 0 ? upper_magnitude : sign | lower_magnitude;
                    faithful = output == lower || output == upper;
                }
                if (!faithful) {
                    ++stats.faithful_failures;
                    update_failure(stats, input, output, lower, upper);
                }
            }
        }
    }
}

void report(int threads, const Stats& stats) {
    const bool pass = stats.significands == kFractionCount - 1
                   && stats.faithful_failures == 0
                   && stats.sign_symmetry_failures == 0
                   && stats.maximum_rne_steps <= 1;
    std::cout << "threads=" << threads << '\n'
              << "nonzero_significands=" << stats.significands << '\n'
              << "rtl_checks=" << stats.rtl_checks << '\n'
              << "rne_matches=" << stats.rne_matches << '\n'
              << "faithful_alternatives=" << stats.faithful_alternatives << '\n'
              << "faithful_failures=" << stats.faithful_failures << '\n'
              << "sign_symmetry_failures="
              << stats.sign_symmetry_failures << '\n'
              << "maximum_rne_steps=" << stats.maximum_rne_steps << '\n'
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
    std::vector<std::unique_ptr<VFP32Recip>> models;
    std::vector<Stats> thread_stats(static_cast<std::size_t>(thread_count));
    contexts.reserve(static_cast<std::size_t>(thread_count));
    models.reserve(static_cast<std::size_t>(thread_count));
    for (int thread = 0; thread < thread_count; ++thread) {
        contexts.push_back(std::make_unique<VerilatedContext>());
        models.push_back(std::make_unique<VFP32Recip>(contexts.back().get()));
    }

#pragma omp parallel
    {
        const int thread = omp_get_thread_num();
        VFP32Recip& dut = *models[static_cast<std::size_t>(thread)];
        Stats& stats = thread_stats[static_cast<std::size_t>(thread)];

#pragma omp for schedule(static)
        for (std::uint32_t fraction = 1; fraction < kFractionCount; ++fraction) {
            const std::uint64_t denominator = 0x00800000u | fraction;
            const std::uint64_t lower_sig = kNumerator / denominator;
            const std::uint64_t remainder = kNumerator % denominator;
            const std::uint64_t upper_sig = lower_sig + (remainder != 0);
            const std::uint32_t lower = (126u << 23)
                                      | (static_cast<std::uint32_t>(lower_sig)
                                         & 0x007fffffu);
            const std::uint32_t upper = (126u << 23)
                                      | (static_cast<std::uint32_t>(upper_sig)
                                         & 0x007fffffu);
            const std::uint32_t rounded_sig =
                rne_significand(lower_sig, remainder, denominator);
            const std::uint32_t rounded = (126u << 23)
                                        | (rounded_sig & 0x007fffffu);
            const std::uint32_t input = (127u << 23) | fraction;
            const std::uint32_t output = evaluate(dut, input);
            const std::uint32_t negative_output =
                evaluate(dut, input | 0x80000000u);

            ++stats.significands;
            stats.rtl_checks += 2;
            if (output != lower && output != upper) {
                ++stats.faithful_failures;
                update_failure(stats, input, output, lower, upper);
            }
            if (negative_output != (output | 0x80000000u)) {
                ++stats.sign_symmetry_failures;
                update_failure(
                    stats, input | 0x80000000u, negative_output,
                    lower | 0x80000000u, upper | 0x80000000u);
            }
            const std::uint64_t rne_steps = distance(output, rounded);
            stats.maximum_rne_steps = std::max(
                stats.maximum_rne_steps, rne_steps);
            if (rne_steps == 0) ++stats.rne_matches;
            else ++stats.faithful_alternatives;
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
