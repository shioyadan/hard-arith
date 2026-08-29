// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0

#include <algorithm>
#include <bit>
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

#include "VFP32Exp.h"
#include "verilated.h"

#ifndef FP32_EXP_ACTIVE_EXPONENT_COUNT
#define FP32_EXP_ACTIVE_EXPONENT_COUNT 32u
#endif

#ifndef FP32_EXP_STD_FUNCTION
#define FP32_EXP_STD_FUNCTION std::exp
#endif

#ifndef FP32_EXP_ORACLE_NAME
#define FP32_EXP_ORACLE_NAME "std::exp"
#endif

#ifdef FP32_EXP_USE_MPFR
#include <mpfr.h>
#ifndef FP32_EXP_MPFR_FUNCTION
#define FP32_EXP_MPFR_FUNCTION mpfr_exp
#endif
#endif

namespace {

constexpr std::uint32_t kCanonicalQnan = 0x7fc00000u;
constexpr std::uint32_t kPositiveInfinity = 0x7f800000u;
constexpr std::uint32_t kMaximumFinite = 0x7f7fffffu;
constexpr std::uint32_t kMinimumSubnormal = 0x00000001u;
constexpr double kMinimumNormal = 0x1p-126;
constexpr double kSubnormalUlp = 0x1p-149;

enum class Mode {
    active,
    full,
};

struct Options {
    Mode mode = Mode::active;
    int threads = 0;
    bool mpfr_near_boundary = false;
};

struct Worst {
    double absolute_ulp = -1.0;
    double signed_ulp = 0.0;
    std::uint32_t input = 0;
    std::uint32_t output = 0;
    std::uint32_t rounded_reference = 0;
    std::uint32_t lower = 0;
    std::uint32_t upper = 0;
};

struct Failure {
    bool valid = false;
    std::uint32_t input = 0;
    std::uint32_t output = 0;
    std::uint32_t lower = 0;
    std::uint32_t upper = 0;
};

struct Stats {
    std::uint64_t checks = 0;
    std::uint64_t finite_checks = 0;
    std::uint64_t faithful_failures = 0;
    std::uint64_t special_checks = 0;
    std::uint64_t special_mismatches = 0;
    std::uint64_t rne_mismatches = 0;
    std::uint64_t normal_checks = 0;
    std::uint64_t subnormal_checks = 0;
    std::uint64_t double_underflow_checks = 0;
    std::uint64_t negative_outputs = 0;
    std::uint64_t max_rne_steps = 0;
    std::uint64_t digest_xor = 0;
    std::uint64_t digest_sum = 0;
    std::uint64_t mpfr_near_candidates = 0;
    std::uint64_t mpfr_near_failures = 0;
    std::uint64_t mpfr_interval_ambiguous = 0;
    std::uint64_t zero_endpoint_analytic_checks = 0;
    std::uint64_t unit_endpoint_analytic_checks = 0;
    std::uint64_t analytic_endpoint_failures = 0;
    std::uint64_t mpfr_max_precision = 0;
    Worst normal_worst{};
    Worst subnormal_worst{};
    Failure first_failure{};
};

std::uint64_t mix64(std::uint64_t value) {
    value += 0x9e3779b97f4a7c15ULL;
    value = (value ^ (value >> 30)) * 0xbf58476d1ce4e5b9ULL;
    value = (value ^ (value >> 27)) * 0x94d049bb133111ebULL;
    return value ^ (value >> 31);
}

std::uint64_t distance(std::uint32_t lhs, std::uint32_t rhs) {
    return lhs >= rhs ? static_cast<std::uint64_t>(lhs - rhs)
                      : static_cast<std::uint64_t>(rhs - lhs);
}

void update_worst(
    Worst& worst,
    double signed_ulp,
    std::uint32_t input,
    std::uint32_t output,
    std::uint32_t rounded_reference,
    std::uint32_t lower,
    std::uint32_t upper) {
    const double absolute = std::abs(signed_ulp);
    if (absolute > worst.absolute_ulp
        || (absolute == worst.absolute_ulp && input < worst.input)) {
        worst = {
            absolute,
            signed_ulp,
            input,
            output,
            rounded_reference,
            lower,
            upper,
        };
    }
}

void update_failure(
    Failure& failure,
    std::uint32_t input,
    std::uint32_t output,
    std::uint32_t lower,
    std::uint32_t upper) {
    if (!failure.valid || input < failure.input) {
        failure = {true, input, output, lower, upper};
    }
}

void merge_worst(Worst& target, const Worst& source) {
    if (source.absolute_ulp > target.absolute_ulp
        || (source.absolute_ulp == target.absolute_ulp
            && source.input < target.input)) {
        target = source;
    }
}

void merge_stats(Stats& target, const Stats& source) {
    target.checks += source.checks;
    target.finite_checks += source.finite_checks;
    target.faithful_failures += source.faithful_failures;
    target.special_checks += source.special_checks;
    target.special_mismatches += source.special_mismatches;
    target.rne_mismatches += source.rne_mismatches;
    target.normal_checks += source.normal_checks;
    target.subnormal_checks += source.subnormal_checks;
    target.double_underflow_checks += source.double_underflow_checks;
    target.negative_outputs += source.negative_outputs;
    target.max_rne_steps =
        std::max(target.max_rne_steps, source.max_rne_steps);
    target.digest_xor ^= source.digest_xor;
    target.digest_sum += source.digest_sum;
    target.mpfr_near_candidates += source.mpfr_near_candidates;
    target.mpfr_near_failures += source.mpfr_near_failures;
    target.mpfr_interval_ambiguous += source.mpfr_interval_ambiguous;
    target.zero_endpoint_analytic_checks +=
        source.zero_endpoint_analytic_checks;
    target.unit_endpoint_analytic_checks +=
        source.unit_endpoint_analytic_checks;
    target.analytic_endpoint_failures +=
        source.analytic_endpoint_failures;
    target.mpfr_max_precision =
        std::max(target.mpfr_max_precision, source.mpfr_max_precision);
    merge_worst(target.normal_worst, source.normal_worst);
    merge_worst(target.subnormal_worst, source.subnormal_worst);
    if (source.first_failure.valid) {
        update_failure(
            target.first_failure,
            source.first_failure.input,
            source.first_failure.output,
            source.first_failure.lower,
            source.first_failure.upper);
    }
}

std::uint32_t input_for_index(Mode mode, std::uint64_t index) {
    if (mode == Mode::full) return static_cast<std::uint32_t>(index);

    const std::uint32_t slot = static_cast<std::uint32_t>(index >> 23);
    const std::uint32_t fraction = static_cast<std::uint32_t>(index)
                                 & 0x007fffffu;
    return ((slot / FP32_EXP_ACTIVE_EXPONENT_COUNT) << 31)
         | ((102u + (slot % FP32_EXP_ACTIVE_EXPONENT_COUNT)) << 23)
         | fraction;
}

#ifdef FP32_EXP_USE_MPFR
void audit_near_boundary(
    float input,
    double binary64_exp,
    std::uint32_t rounded_bits,
    std::uint32_t output_bits,
    Stats& stats) {
    constexpr double kNearThreshold = 0x1p-20;

    // exp(x) is strictly positive.  Values near the zero grid point always
    // have the exact binary32 bracketing pair [0, minimum subnormal], so they
    // do not need an individual MPFR call (this region contains many inputs).
    if (binary64_exp == 0.0) {
        ++stats.zero_endpoint_analytic_checks;
        if (output_bits != 0 && output_bits != kMinimumSubnormal) {
            ++stats.analytic_endpoint_failures;
        }
        return;
    }
    if (!(binary64_exp > 0.0) || !std::isfinite(binary64_exp)) return;
    if (rounded_bits == 0) {
        if (binary64_exp / kSubnormalUlp <= kNearThreshold) {
            ++stats.zero_endpoint_analytic_checks;
            if (output_bits != 0 && output_bits != kMinimumSubnormal) {
                ++stats.analytic_endpoint_failures;
            }
        }
        return;
    }
    if (rounded_bits >= kPositiveInfinity) return;

    const float rounded = std::bit_cast<float>(rounded_bits);
    const double ulp = binary64_exp >= kMinimumNormal
        ? std::ldexp(1.0, std::ilogb(binary64_exp) - 23)
        : kSubnormalUlp;
    const double grid_distance =
        std::abs(binary64_exp - static_cast<double>(rounded)) / ulp;
    if (grid_distance > kNearThreshold) return;

    // A large set of tiny |x| values maps very close to the exact grid point
    // 1.  Monotonicity gives the bracket without one MPFR call per input:
    // x<0 -> [prev(1),1], x=0 -> [1,1], x>0 -> [1,next(1)].
    if (rounded_bits == 0x3f800000u) {
        ++stats.unit_endpoint_analytic_checks;
        std::uint32_t lower = 0x3f800000u;
        std::uint32_t upper = 0x3f800000u;
        if (input > 0.0f) upper = 0x3f800001u;
        if (input < 0.0f) lower = 0x3f7fffffu;
        if (output_bits != lower && output_bits != upper) {
            ++stats.analytic_endpoint_failures;
        }
        return;
    }

    ++stats.mpfr_near_candidates;
    std::uint32_t certified_lower = 0;
    std::uint32_t certified_upper = 0;
    bool certified = false;
    for (mpfr_prec_t precision = 256; precision <= 4096; precision *= 2) {
        mpfr_t argument;
        mpfr_t lower_bound;
        mpfr_t upper_bound;
        mpfr_init2(argument, precision);
        mpfr_init2(lower_bound, precision);
        mpfr_init2(upper_bound, precision);
        mpfr_set_flt(argument, input, MPFR_RNDN);
        FP32_EXP_MPFR_FUNCTION(lower_bound, argument, MPFR_RNDD);
        FP32_EXP_MPFR_FUNCTION(upper_bound, argument, MPFR_RNDU);

        const std::uint32_t lower_from_lower = std::bit_cast<std::uint32_t>(
            mpfr_get_flt(lower_bound, MPFR_RNDD));
        const std::uint32_t lower_from_upper = std::bit_cast<std::uint32_t>(
            mpfr_get_flt(upper_bound, MPFR_RNDD));
        const std::uint32_t upper_from_lower = std::bit_cast<std::uint32_t>(
            mpfr_get_flt(lower_bound, MPFR_RNDU));
        const std::uint32_t upper_from_upper = std::bit_cast<std::uint32_t>(
            mpfr_get_flt(upper_bound, MPFR_RNDU));
        mpfr_clear(argument);
        mpfr_clear(lower_bound);
        mpfr_clear(upper_bound);

        stats.mpfr_max_precision = std::max(
            stats.mpfr_max_precision,
            static_cast<std::uint64_t>(precision));
        if (lower_from_lower == lower_from_upper
            && upper_from_lower == upper_from_upper) {
            certified_lower = lower_from_lower;
            certified_upper = upper_from_lower;
            certified = true;
            break;
        }
    }

    if (!certified) {
        ++stats.mpfr_interval_ambiguous;
        return;
    }
    if (output_bits != certified_lower && output_bits != certified_upper) {
        ++stats.mpfr_near_failures;
    }
}
#endif

void check_one(
    VFP32Exp& dut,
    std::uint32_t input_bits,
    const Options& options,
    Stats& stats) {
    dut.x = input_bits;
    dut.eval();
    const std::uint32_t output_bits = dut.result;
    ++stats.checks;

    const std::uint64_t pair =
        (static_cast<std::uint64_t>(input_bits) << 32) | output_bits;
    stats.digest_xor ^= mix64(pair);
    stats.digest_sum += mix64(pair ^ 0xd1b54a32d192ed03ULL);

    if ((output_bits & 0x80000000u) != 0) ++stats.negative_outputs;

    const std::uint32_t input_exponent = (input_bits >> 23) & 0xffu;
    const std::uint32_t input_fraction = input_bits & 0x007fffffu;
    if (input_exponent == 0xffu) {
        ++stats.special_checks;
        const std::uint32_t expected = input_fraction != 0
            ? kCanonicalQnan
            : ((input_bits >> 31) != 0 ? 0u : kPositiveInfinity);
        if (output_bits != expected) {
            ++stats.special_mismatches;
            update_failure(
                stats.first_failure,
                input_bits,
                output_bits,
                expected,
                expected);
        }
        return;
    }

    ++stats.finite_checks;
    const float input = std::bit_cast<float>(input_bits);
    const double exact = FP32_EXP_STD_FUNCTION(static_cast<double>(input));

    std::uint32_t rounded_bits = 0;
    std::uint32_t lower = 0;
    std::uint32_t upper = 0;
    if (exact == 0.0) {
        // The real exp(x) is positive.  A binary64 underflow therefore lies
        // between +0 and the minimum positive binary32 subnormal.
        ++stats.double_underflow_checks;
        rounded_bits = 0;
        lower = 0;
        upper = kMinimumSubnormal;
    } else if (std::isinf(exact)) {
        rounded_bits = kPositiveInfinity;
        lower = kMaximumFinite;
        upper = kPositiveInfinity;
    } else {
        const float rounded = static_cast<float>(exact);
        rounded_bits = std::bit_cast<std::uint32_t>(rounded);
        if (std::isinf(rounded)) {
            lower = kMaximumFinite;
            upper = kPositiveInfinity;
        } else if (static_cast<double>(rounded) < exact) {
            lower = rounded_bits;
            upper = rounded_bits + 1;
        } else if (static_cast<double>(rounded) > exact) {
            lower = rounded_bits - 1;
            upper = rounded_bits;
        } else {
            lower = rounded_bits;
            upper = rounded_bits;
        }
    }

#ifdef FP32_EXP_USE_MPFR
    if (options.mpfr_near_boundary) {
        audit_near_boundary(
            input,
            exact,
            rounded_bits,
            output_bits,
            stats);
    }
#else
    (void)options;
#endif

    if (output_bits != rounded_bits) ++stats.rne_mismatches;
    stats.max_rne_steps = std::max(
        stats.max_rne_steps, distance(output_bits, rounded_bits));

    if (output_bits != lower && output_bits != upper) {
        ++stats.faithful_failures;
        update_failure(
            stats.first_failure,
            input_bits,
            output_bits,
            lower,
            upper);
    }

    if (!(exact > 0.0) || !std::isfinite(exact)) return;
    const float output = std::bit_cast<float>(output_bits);
    if (!std::isfinite(output)) return;

    const bool normal = exact >= kMinimumNormal;
    const double ulp = normal
        ? std::ldexp(1.0, std::ilogb(exact) - 23)
        : kSubnormalUlp;
    const double signed_ulp = (static_cast<double>(output) - exact) / ulp;
    if (normal) {
        ++stats.normal_checks;
        update_worst(
            stats.normal_worst,
            signed_ulp,
            input_bits,
            output_bits,
            rounded_bits,
            lower,
            upper);
    } else {
        ++stats.subnormal_checks;
        update_worst(
            stats.subnormal_worst,
            signed_ulp,
            input_bits,
            output_bits,
            rounded_bits,
            lower,
            upper);
    }
}

Options parse_options(int argc, char** argv) {
    Options options;
    for (int index = 1; index < argc; ++index) {
        const std::string_view argument = argv[index];
        if (argument == "--active") {
            options.mode = Mode::active;
        } else if (argument == "--full") {
            options.mode = Mode::full;
        } else if (argument.starts_with("--threads=")) {
            const std::string_view number = argument.substr(10);
            char* end = nullptr;
            const long value = std::strtol(number.data(), &end, 10);
            if (end != number.data() + number.size() || value <= 0) {
                std::cerr << "invalid thread count: " << number << '\n';
                std::exit(2);
            }
            options.threads = static_cast<int>(value);
        } else if (argument == "--mpfr-near-boundary") {
#ifdef FP32_EXP_USE_MPFR
            options.mpfr_near_boundary = true;
#else
            std::cerr << "--mpfr-near-boundary requires a build with "
                         "-DFP32_EXP_USE_MPFR and -lmpfr\n";
            std::exit(2);
#endif
        } else {
            std::cerr << "usage: " << argv[0]
                      << " [--active|--full] [--threads=N]"
                         " [--mpfr-near-boundary]\n";
            std::exit(2);
        }
    }
    return options;
}

void print_worst(std::string_view prefix, const Worst& worst) {
    std::cout << prefix << "_checks_present="
              << (worst.absolute_ulp >= 0.0 ? 1 : 0) << '\n';
    if (worst.absolute_ulp < 0.0) return;
    std::cout << std::setprecision(18)
              << prefix << "_worst_absolute_ulp=" << worst.absolute_ulp << '\n'
              << prefix << "_worst_signed_ulp=" << worst.signed_ulp << '\n'
              << prefix << "_worst_input_bits=0x" << std::hex
              << std::setw(8) << std::setfill('0') << worst.input << '\n'
              << prefix << "_worst_output_bits=0x" << std::setw(8)
              << worst.output << '\n'
              << prefix << "_worst_reference_bits=0x" << std::setw(8)
              << worst.rounded_reference << '\n'
              << prefix << "_worst_lower_bits=0x" << std::setw(8)
              << worst.lower << '\n'
              << prefix << "_worst_upper_bits=0x" << std::setw(8)
              << worst.upper << '\n'
              << std::dec << std::setfill(' ')
              << prefix << "_worst_input=" << std::hexfloat
              << std::bit_cast<float>(worst.input) << std::defaultfloat << '\n';
}

void report(const Options& options, int threads, const Stats& stats) {
    const bool pass = stats.faithful_failures == 0
                   && stats.special_mismatches == 0
                   && stats.negative_outputs == 0
                   && stats.mpfr_near_failures == 0
                   && stats.analytic_endpoint_failures == 0
                   && stats.mpfr_interval_ambiguous == 0;
    std::cout << "oracle=" FP32_EXP_ORACLE_NAME
                 "(binary64); near-grid cases checked with optional MPFR; not a formal proof\n"
              << "mode=" << (options.mode == Mode::full ? "full" : "active")
              << '\n'
              << "threads=" << threads << '\n'
              << "checks=" << stats.checks << '\n'
              << "finite_checks=" << stats.finite_checks << '\n'
              << "faithful_failures=" << stats.faithful_failures << '\n'
              << "special_checks=" << stats.special_checks << '\n'
              << "special_mismatches=" << stats.special_mismatches << '\n'
              << "rne_mismatches=" << stats.rne_mismatches << '\n'
              << "max_rne_steps=" << stats.max_rne_steps << '\n'
              << "normal_checks=" << stats.normal_checks << '\n'
              << "subnormal_checks=" << stats.subnormal_checks << '\n'
              << "double_underflow_checks="
              << stats.double_underflow_checks << '\n'
              << "negative_outputs=" << stats.negative_outputs << '\n'
              << "digest_xor=0x" << std::hex << std::setw(16)
              << std::setfill('0') << stats.digest_xor << '\n'
              << "digest_sum=0x" << std::setw(16) << stats.digest_sum << '\n'
              << std::dec << std::setfill(' ')
              << "mpfr_near_boundary_enabled="
              << (options.mpfr_near_boundary ? 1 : 0) << '\n';
    if (options.mpfr_near_boundary) {
        std::cout
            << "mpfr_near_threshold_ulp=" << std::hexfloat << 0x1p-20
            << std::defaultfloat << '\n'
            << "mpfr_near_candidates=" << stats.mpfr_near_candidates << '\n'
            << "mpfr_near_failures=" << stats.mpfr_near_failures << '\n'
            << "mpfr_interval_ambiguous="
            << stats.mpfr_interval_ambiguous << '\n'
            << "zero_endpoint_analytic_checks="
            << stats.zero_endpoint_analytic_checks << '\n'
            << "unit_endpoint_analytic_checks="
            << stats.unit_endpoint_analytic_checks << '\n'
            << "near_candidates_total="
            << (stats.mpfr_near_candidates
                + stats.zero_endpoint_analytic_checks
                + stats.unit_endpoint_analytic_checks) << '\n'
            << "analytic_endpoint_failures="
            << stats.analytic_endpoint_failures << '\n'
            << "mpfr_max_precision=" << stats.mpfr_max_precision << '\n';
    }
    print_worst("normal", stats.normal_worst);
    print_worst("subnormal", stats.subnormal_worst);
    std::cout << "first_failure_present="
              << (stats.first_failure.valid ? 1 : 0) << '\n';
    if (stats.first_failure.valid) {
        std::cout << "first_failure_input_bits=0x" << std::hex
                  << std::setw(8) << std::setfill('0')
                  << stats.first_failure.input << '\n'
                  << "first_failure_output_bits=0x" << std::setw(8)
                  << stats.first_failure.output << '\n'
                  << "first_failure_lower_bits=0x" << std::setw(8)
                  << stats.first_failure.lower << '\n'
                  << "first_failure_upper_bits=0x" << std::setw(8)
                  << stats.first_failure.upper << '\n'
                  << std::dec << std::setfill(' ');
    }
    std::cout << "pass=" << (pass ? 1 : 0) << '\n';
}

}  // namespace

int main(int argc, char** argv) {
    const Options options = parse_options(argc, argv);
    if (options.threads > 0) omp_set_num_threads(options.threads);
    const int threads = omp_get_max_threads();
    const std::uint64_t count = options.mode == Mode::full
        ? (1ULL << 32)
        : (2ULL * FP32_EXP_ACTIVE_EXPONENT_COUNT << 23);

    // Construct models and their independent contexts serially.  Each model
    // is then evaluated by exactly one OpenMP worker.
    std::vector<std::unique_ptr<VerilatedContext>> contexts;
    std::vector<std::unique_ptr<VFP32Exp>> models;
    contexts.reserve(static_cast<std::size_t>(threads));
    models.reserve(static_cast<std::size_t>(threads));
    for (int thread = 0; thread < threads; ++thread) {
        contexts.push_back(std::make_unique<VerilatedContext>());
        models.push_back(std::make_unique<VFP32Exp>(contexts.back().get()));
    }

    Stats total;
#pragma omp parallel num_threads(threads)
    {
        const int thread = omp_get_thread_num();
        Verilated::threadContextp(
            contexts[static_cast<std::size_t>(thread)].get());
        VFP32Exp& dut = *models[static_cast<std::size_t>(thread)];
        Stats local;
#pragma omp for schedule(static)
        for (std::uint64_t index = 0; index < count; ++index) {
            check_one(
                dut,
                input_for_index(options.mode, index),
                options,
                local);
        }
        dut.final();
#pragma omp critical
        merge_stats(total, local);
    }

    report(options, threads, total);
    const bool pass = total.faithful_failures == 0
                   && total.special_mismatches == 0
                   && total.negative_outputs == 0
                   && total.mpfr_near_failures == 0
                   && total.analytic_endpoint_failures == 0
                   && total.mpfr_interval_ambiguous == 0;
    return pass ? 0 : 1;
}
