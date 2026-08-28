// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0

#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <iostream>

#include "VFP32Recip.h"
#include "verilated.h"

namespace {

struct Failure {
    bool valid = false;
    std::uint32_t previous_input = 0;
    std::uint32_t previous_output = 0;
    std::uint32_t input = 0;
    std::uint32_t output = 0;
};

struct Stats {
    std::uint64_t mantissa_comparisons = 0;
    std::uint64_t exponent_boundary_comparisons = 0;
    std::uint64_t equal_output_pairs = 0;
    std::uint64_t monotonicity_violations = 0;
    std::uint64_t maximum_increase_steps = 0;
    Failure first_failure{};
};

std::uint32_t evaluate(VFP32Recip& dut, std::uint32_t input) {
    dut.x = input;
    dut.eval();
    return dut.result;
}

std::uint32_t ordered_key(std::uint32_t bits) {
    return (bits & 0x80000000u) != 0 ? ~bits : bits | 0x80000000u;
}

void check_pair(
    std::uint32_t previous_input,
    std::uint32_t previous_output,
    std::uint32_t input,
    std::uint32_t output,
    bool mantissa_pair,
    Stats& stats) {
    if (mantissa_pair) ++stats.mantissa_comparisons;
    else ++stats.exponent_boundary_comparisons;

    const std::uint32_t previous_key = ordered_key(previous_output);
    const std::uint32_t output_key = ordered_key(output);
    if (output_key == previous_key) {
        ++stats.equal_output_pairs;
        return;
    }
    // 入力は数値の昇順なので、逆数の出力は非増加でなければならない。
    if (output_key < previous_key) return;

    ++stats.monotonicity_violations;
    stats.maximum_increase_steps = std::max(
        stats.maximum_increase_steps,
        static_cast<std::uint64_t>(output_key - previous_key));
    if (!stats.first_failure.valid) {
        stats.first_failure = {
            true, previous_input, previous_output, input, output,
        };
    }
}

void check_positive_mantissa(VFP32Recip& dut, Stats& stats) {
    std::uint32_t previous_input = 127u << 23;
    std::uint32_t previous_output = evaluate(dut, previous_input);
    for (std::uint32_t fraction = 1; fraction < (1u << 23); ++fraction) {
        const std::uint32_t input = (127u << 23) | fraction;
        const std::uint32_t output = evaluate(dut, input);
        check_pair(
            previous_input, previous_output, input, output, true, stats);
        previous_input = input;
        previous_output = output;
    }
}

void check_negative_mantissa(VFP32Recip& dut, Stats& stats) {
    std::uint32_t previous_input = 0xbfffffffu;
    std::uint32_t previous_output = evaluate(dut, previous_input);
    for (std::uint32_t fraction = 0x007ffffeu;; --fraction) {
        const std::uint32_t input = 0xbf800000u | fraction;
        const std::uint32_t output = evaluate(dut, input);
        check_pair(
            previous_input, previous_output, input, output, true, stats);
        previous_input = input;
        previous_output = output;
        if (fraction == 0) break;
    }
}

void check_exponent_boundaries(VFP32Recip& dut, Stats& stats) {
    // 正領域：+0、subnormal、normalの各binade、+Infの順に進む。
    const std::uint32_t positive_boundaries[][2] = {
        {0x00000000u, 0x00000001u},
        {0x007fffffu, 0x00800000u},
        {0x7f7fffffu, 0x7f800000u},
    };
    for (const auto& pair : positive_boundaries) {
        check_pair(
            pair[0], evaluate(dut, pair[0]),
            pair[1], evaluate(dut, pair[1]), false, stats);
    }
    for (std::uint32_t exponent = 1; exponent < 254; ++exponent) {
        const std::uint32_t previous_input = (exponent << 23) | 0x007fffffu;
        const std::uint32_t input = (exponent + 1) << 23;
        check_pair(
            previous_input, evaluate(dut, previous_input),
            input, evaluate(dut, input), false, stats);
    }

    // 負領域：-Infから-0へ数値の昇順に進む。
    check_pair(
        0xff800000u, evaluate(dut, 0xff800000u),
        0xff7fffffu, evaluate(dut, 0xff7fffffu), false, stats);
    for (std::uint32_t exponent = 254; exponent > 1; --exponent) {
        const std::uint32_t previous_input = 0x80000000u | (exponent << 23);
        const std::uint32_t input =
            0x80000000u | ((exponent - 1) << 23) | 0x007fffffu;
        check_pair(
            previous_input, evaluate(dut, previous_input),
            input, evaluate(dut, input), false, stats);
    }
    check_pair(
        0x80800000u, evaluate(dut, 0x80800000u),
        0x807fffffu, evaluate(dut, 0x807fffffu), false, stats);
    check_pair(
        0x80000001u, evaluate(dut, 0x80000001u),
        0x80000000u, evaluate(dut, 0x80000000u), false, stats);
}

void report(const Stats& stats) {
    const bool pass = stats.mantissa_comparisons
                          == 2 * ((std::uint64_t{1} << 23) - 1)
                   && stats.exponent_boundary_comparisons == 512
                   && stats.monotonicity_violations == 0;
    std::cout << "mantissa_comparisons=" << stats.mantissa_comparisons << '\n'
              << "exponent_boundary_comparisons="
              << stats.exponent_boundary_comparisons << '\n'
              << "equal_output_pairs=" << stats.equal_output_pairs << '\n'
              << "monotonicity_violations="
              << stats.monotonicity_violations << '\n'
              << "maximum_increase_steps="
              << stats.maximum_increase_steps << '\n'
              << "first_failure_present="
              << (stats.first_failure.valid ? 1 : 0) << '\n';
    if (stats.first_failure.valid) {
        std::cout << "previous_input=0x" << std::hex << std::setw(8)
                  << std::setfill('0') << stats.first_failure.previous_input << '\n'
                  << "previous_output=0x" << std::setw(8)
                  << stats.first_failure.previous_output << '\n'
                  << "input=0x" << std::setw(8)
                  << stats.first_failure.input << '\n'
                  << "output=0x" << std::setw(8)
                  << stats.first_failure.output << '\n'
                  << std::dec << std::setfill(' ');
    }
    std::cout << "pass=" << (pass ? 1 : 0) << '\n';
    if (!pass) std::exit(1);
}

}  // namespace

int main() {
    VerilatedContext context;
    VFP32Recip dut{&context};
    Stats stats;
    check_positive_mantissa(dut, stats);
    check_negative_mantissa(dut, stats);
    check_exponent_boundaries(dut, stats);
    report(stats);
    return 0;
}
