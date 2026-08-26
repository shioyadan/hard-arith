// Copyright 2026 Ryota Shioya and Toru Koizumi
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

#include "VFP32Exp.h"
#include "verilated.h"

namespace {

// IEEE 754 binary32 の totalOrder と同じ向きにビット列を変換すると、
// 非 NaN 入力はこの連続区間になる。区間の両端は -inf と +inf である。
constexpr std::uint32_t kFirstOrderedKey = 0x007fffffu;
constexpr std::uint32_t kLastOrderedKey = 0xff800000u;
constexpr std::uint64_t kOrderedInputCount =
    static_cast<std::uint64_t>(kLastOrderedKey) - kFirstOrderedKey + 1;
constexpr std::uint64_t kAdjacentComparisonCount = kOrderedInputCount - 1;

struct Options {
    int threads = 0;
};

struct Failure {
    bool valid = false;
    bool unordered_output = false;
    std::uint32_t previous_key = 0;
    std::uint32_t previous_input = 0;
    std::uint32_t previous_output = 0;
    std::uint32_t input = 0;
    std::uint32_t output = 0;
};

struct Stats {
    std::uint64_t comparisons = 0;
    std::uint64_t equal_output_pairs = 0;
    std::uint64_t monotonicity_violations = 0;
    std::uint64_t unordered_output_pairs = 0;
    std::uint64_t negative_violations = 0;
    std::uint64_t positive_violations = 0;
    std::uint64_t maximum_drop_steps = 0;
    Failure first_failure{};
};

std::uint32_t bits_from_ordered_key(std::uint32_t key) {
    return (key & 0x80000000u) != 0 ? key & 0x7fffffffu : ~key;
}

std::uint32_t ordered_key(std::uint32_t bits) {
    return (bits & 0x80000000u) != 0 ? ~bits : bits | 0x80000000u;
}

bool is_nan(std::uint32_t bits) {
    return (bits & 0x7f800000u) == 0x7f800000u
        && (bits & 0x007fffffu) != 0;
}

std::uint32_t evaluate(VFP32Exp& dut, std::uint32_t input) {
    dut.x = input;
    dut.eval();
    return dut.result;
}

void update_first_failure(Stats& stats, const Failure& failure) {
    if (!stats.first_failure.valid
        || failure.previous_key < stats.first_failure.previous_key) {
        stats.first_failure = failure;
    }
}

void check_pair(
    std::uint32_t previous_key,
    std::uint32_t previous_input,
    std::uint32_t previous_output,
    std::uint32_t input,
    std::uint32_t output,
    Stats& stats) {
    ++stats.comparisons;
    if (is_nan(previous_output) || is_nan(output)) {
        ++stats.unordered_output_pairs;
        update_first_failure(stats, {
            true,
            true,
            previous_key,
            previous_input,
            previous_output,
            input,
            output,
        });
        return;
    }

    const std::uint32_t previous_output_key = ordered_key(previous_output);
    const std::uint32_t output_key = ordered_key(output);
    if (previous_output_key == output_key) {
        ++stats.equal_output_pairs;
        return;
    }
    if (previous_output_key < output_key) return;

    ++stats.monotonicity_violations;
    if ((previous_input & 0x80000000u) != 0) {
        ++stats.negative_violations;
    } else {
        ++stats.positive_violations;
    }
    stats.maximum_drop_steps = std::max(
        stats.maximum_drop_steps,
        static_cast<std::uint64_t>(previous_output_key - output_key));
    update_first_failure(stats, {
        true,
        false,
        previous_key,
        previous_input,
        previous_output,
        input,
        output,
    });
}

void merge_stats(Stats& target, const Stats& source) {
    target.comparisons += source.comparisons;
    target.equal_output_pairs += source.equal_output_pairs;
    target.monotonicity_violations += source.monotonicity_violations;
    target.unordered_output_pairs += source.unordered_output_pairs;
    target.negative_violations += source.negative_violations;
    target.positive_violations += source.positive_violations;
    target.maximum_drop_steps = std::max(
        target.maximum_drop_steps, source.maximum_drop_steps);
    if (source.first_failure.valid) {
        update_first_failure(target, source.first_failure);
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

void report(int threads, const Stats& stats) {
    const bool pass = stats.comparisons == kAdjacentComparisonCount
                   && stats.monotonicity_violations == 0
                   && stats.unordered_output_pairs == 0;
    std::cout << "threads=" << threads << '\n'
              << "ordered_non_nan_inputs=" << kOrderedInputCount << '\n'
              << "adjacent_comparisons=" << stats.comparisons << '\n'
              << "equal_output_pairs=" << stats.equal_output_pairs << '\n'
              << "monotonicity_violations="
              << stats.monotonicity_violations << '\n'
              << "unordered_output_pairs=" << stats.unordered_output_pairs
              << '\n'
              << "negative_violations=" << stats.negative_violations << '\n'
              << "positive_violations=" << stats.positive_violations << '\n'
              << "maximum_drop_steps=" << stats.maximum_drop_steps << '\n'
              << "first_failure_present="
              << (stats.first_failure.valid ? 1 : 0) << '\n';
    if (stats.first_failure.valid) {
        std::cout << "first_failure_kind="
                  << (stats.first_failure.unordered_output
                      ? "unordered_output" : "decreasing_output")
                  << '\n'
                  << "previous_input=0x" << std::hex << std::setw(8)
                  << std::setfill('0') << stats.first_failure.previous_input
                  << '\n'
                  << "previous_output=0x" << std::setw(8)
                  << stats.first_failure.previous_output << '\n'
                  << "input=0x" << std::setw(8)
                  << stats.first_failure.input << '\n'
                  << "output=0x" << std::setw(8)
                  << stats.first_failure.output << '\n'
                  << std::dec << std::setfill(' ');
    }
    std::cout << "pass=" << (pass ? 1 : 0) << '\n';
}

}  // namespace

int main(int argc, char** argv) {
    const Options options = parse_options(argc, argv);
    if (options.threads > 0) omp_set_num_threads(options.threads);
    omp_set_dynamic(0);
    const int maximum_threads = omp_get_max_threads();

    // Verilated model はスレッド間で共有せず、それぞれ独立した context と
    // model を持つ。各 worker に連続区間を割り当てることで、区間の先頭以外は
    // 一つ前の評価結果を再利用し、各入力をほぼ一度だけ評価する。
    std::vector<std::unique_ptr<VerilatedContext>> contexts;
    std::vector<std::unique_ptr<VFP32Exp>> models;
    contexts.reserve(static_cast<std::size_t>(maximum_threads));
    models.reserve(static_cast<std::size_t>(maximum_threads));
    for (int thread = 0; thread < maximum_threads; ++thread) {
        contexts.push_back(std::make_unique<VerilatedContext>());
        models.push_back(std::make_unique<VFP32Exp>(contexts.back().get()));
    }

    Stats total;
    int actual_threads = 0;
#pragma omp parallel num_threads(maximum_threads)
    {
        const int thread = omp_get_thread_num();
        const int team_size = omp_get_num_threads();
#pragma omp single
        actual_threads = team_size;
        Verilated::threadContextp(
            contexts[static_cast<std::size_t>(thread)].get());
        VFP32Exp& dut = *models[static_cast<std::size_t>(thread)];
        Stats local;

        const std::uint64_t begin = kAdjacentComparisonCount
            * static_cast<std::uint64_t>(thread)
            / static_cast<std::uint64_t>(team_size);
        const std::uint64_t end = kAdjacentComparisonCount
            * static_cast<std::uint64_t>(thread + 1)
            / static_cast<std::uint64_t>(team_size);
        std::uint32_t previous_key = static_cast<std::uint32_t>(
            static_cast<std::uint64_t>(kFirstOrderedKey) + begin);
        std::uint32_t previous_input = bits_from_ordered_key(previous_key);
        std::uint32_t previous_output = evaluate(dut, previous_input);
        for (std::uint64_t ordinal = begin; ordinal < end; ++ordinal) {
            const std::uint32_t key = static_cast<std::uint32_t>(
                static_cast<std::uint64_t>(kFirstOrderedKey) + ordinal + 1);
            const std::uint32_t input = bits_from_ordered_key(key);
            const std::uint32_t output = evaluate(dut, input);
            check_pair(
                previous_key,
                previous_input,
                previous_output,
                input,
                output,
                local);
            previous_key = key;
            previous_input = input;
            previous_output = output;
        }
        dut.final();
#pragma omp critical
        merge_stats(total, local);
    }

    report(actual_threads, total);
    const bool pass = total.comparisons == kAdjacentComparisonCount
                   && total.monotonicity_violations == 0
                   && total.unordered_output_pairs == 0;
    return pass ? 0 : 1;
}
