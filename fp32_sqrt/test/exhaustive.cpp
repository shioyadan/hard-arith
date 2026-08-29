// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <memory>
#include <vector>

#include <omp.h>

#include "VFP32Sqrt.h"
#include "verilated.h"

namespace {

constexpr std::uint32_t kFractionCount = 1u << 23;
constexpr std::uint64_t kChecks = 2ull * kFractionCount;

struct Bounds {
    std::uint32_t lower;
    std::uint32_t upper;
    std::uint32_t rne;
    std::uint64_t radicand;
};

std::uint32_t evaluate(VFP32Sqrt& dut, std::uint32_t input) {
    dut.x = input;
    dut.eval();
    return dut.result;
}

std::uint32_t integer_sqrt(std::uint64_t value) {
    std::uint64_t root = static_cast<std::uint64_t>(
        std::sqrt(static_cast<long double>(value)));
    while ((root + 1) * (root + 1) <= value) ++root;
    while (root * root > value) --root;
    return static_cast<std::uint32_t>(root);
}

Bounds positive_normal_bounds(std::uint32_t input) {
    const std::uint32_t exponent = (input >> 23) & 0xffu;
    const std::uint32_t fraction = input & 0x007fffffu;
    const std::uint32_t parity = (~exponent) & 1u;
    const std::uint32_t significand = 0x00800000u | fraction;
    const std::uint64_t radicand =
        static_cast<std::uint64_t>(significand) << (23 + parity);
    const std::uint32_t root = integer_sqrt(radicand);
    const std::uint64_t remainder =
        radicand - static_cast<std::uint64_t>(root) * root;
    const std::uint32_t output_exponent =
        (exponent + 127u - parity) >> 1;
    const std::uint32_t lower =
        (output_exponent << 23) | (root & 0x007fffffu);
    const std::uint32_t upper = remainder == 0 ? lower : lower + 1;
    const std::uint32_t rne = lower + (remainder > root);
    return { lower, upper, rne, radicand };
}

std::uint32_t reference(std::uint32_t input) {
    const std::uint32_t sign = input >> 31;
    const std::uint32_t exponent = (input >> 23) & 0xffu;
    const std::uint32_t fraction = input & 0x007fffffu;
    if (exponent == 0xffu) {
        if (fraction != 0 || sign != 0) return 0x7fc00000u;
        return 0x7f800000u;
    }
    if (exponent == 0) return sign << 31;
    if (sign != 0) return 0x7fc00000u;
    return positive_normal_bounds(input).rne;
}

}  // namespace

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    omp_set_dynamic(0);
    const int threads = omp_get_max_threads();
    std::vector<std::unique_ptr<VerilatedContext>> contexts;
    std::vector<std::unique_ptr<VFP32Sqrt>> models;
    contexts.reserve(threads);
    models.reserve(threads);
    for (int thread = 0; thread < threads; ++thread) {
        contexts.push_back(std::make_unique<VerilatedContext>());
        models.push_back(
            std::make_unique<VFP32Sqrt>(contexts.back().get()));
    }

    std::vector<std::uint32_t> outputs(kChecks);
    std::uint64_t faithful_failures = 0;
    std::uint64_t rne_matches = 0;
    std::uint64_t maximum_rne_steps = 0;
    long double maximum_absolute_error_ulp = 0;

#pragma omp parallel for schedule(static) reduction(+:faithful_failures,rne_matches) reduction(max:maximum_rne_steps,maximum_absolute_error_ulp)
    for (std::uint64_t linear = 0; linear < kChecks; ++linear) {
        const int thread = omp_get_thread_num();
        const std::uint32_t parity = static_cast<std::uint32_t>(linear >> 23);
        const std::uint32_t fraction =
            static_cast<std::uint32_t>(linear) & 0x007fffffu;
        const std::uint32_t input = ((127u + parity) << 23) | fraction;
        const std::uint32_t output = evaluate(*models[thread], input);
        outputs[linear] = output;
        const Bounds bounds = positive_normal_bounds(input);
        faithful_failures += output != bounds.lower && output != bounds.upper;
        const std::uint64_t steps = output >= bounds.rne
            ? output - bounds.rne : bounds.rne - output;
        maximum_rne_steps = std::max(maximum_rne_steps, steps);
        rne_matches += steps == 0;

        const std::uint32_t output_exponent = (output >> 23) & 0xffu;
        const std::uint32_t output_sig =
            0x00800000u | (output & 0x007fffffu);
        const long double output_coordinate = output_exponent == 127
            ? static_cast<long double>(output_sig)
            : 2.0L * output_sig;
        const long double exact_coordinate =
            std::sqrt(static_cast<long double>(bounds.radicand));
        maximum_absolute_error_ulp = std::max(
            maximum_absolute_error_ulp,
            std::fabs(output_coordinate - exact_coordinate));
    }

    std::uint64_t monotonicity_violations = 0;
    for (std::uint32_t parity = 0; parity < 2; ++parity) {
        const std::uint64_t begin = static_cast<std::uint64_t>(parity) << 23;
        for (std::uint32_t fraction = 1; fraction < kFractionCount; ++fraction) {
            monotonicity_violations +=
                outputs[begin + fraction] < outputs[begin + fraction - 1];
        }
    }
    monotonicity_violations +=
        outputs[kFractionCount - 1] > outputs[kFractionCount];

    std::uint64_t exponent_boundary_violations = 0;
    VFP32Sqrt& scalar_dut = *models.front();
    for (std::uint32_t exponent = 1; exponent < 254; ++exponent) {
        const std::uint32_t lower_input =
            (exponent << 23) | 0x007fffffu;
        const std::uint32_t upper_input = (exponent + 1) << 23;
        exponent_boundary_violations +=
            evaluate(scalar_dut, lower_input) > evaluate(scalar_dut, upper_input);
    }

    constexpr std::uint32_t special_inputs[] = {
        0x00000000u, 0x80000000u, 0x00000001u, 0x007fffffu,
        0x80000001u, 0x807fffffu, 0x7f800000u, 0xff800000u,
        0x7fc00000u, 0xffc12345u, 0xbf800000u,
    };
    std::uint64_t special_failures = 0;
    for (const std::uint32_t input : special_inputs) {
        special_failures += evaluate(scalar_dut, input) != reference(input);
    }

    const bool pass = faithful_failures == 0 && maximum_rne_steps <= 1
                   && monotonicity_violations == 0
                   && exponent_boundary_violations == 0
                   && special_failures == 0;
    std::cout << "threads=" << threads << '\n'
              << "parity_significands=" << kChecks << '\n'
              << "rne_matches=" << rne_matches << '\n'
              << "faithful_alternatives=" << kChecks - rne_matches << '\n'
              << "faithful_failures=" << faithful_failures << '\n'
              << "maximum_rne_steps=" << maximum_rne_steps << '\n'
              << std::fixed << std::setprecision(12)
              << "maximum_absolute_error_ulp="
              << maximum_absolute_error_ulp << '\n'
              << "monotonicity_violations=" << monotonicity_violations << '\n'
              << "exponent_boundary_violations="
              << exponent_boundary_violations << '\n'
              << "special_failures=" << special_failures << '\n'
              << "pass=" << pass << '\n';
    return pass ? 0 : 1;
}
