// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0
#include "VFP64FMA.h"
#include "verilated.h"
#include "reference.hpp"
#include <array>
#include <cfenv>
#include <cmath>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>

static constexpr uint64_t sign_bit = UINT64_C(0x8000000000000000);
static constexpr uint64_t fraction_mask = UINT64_C(0x000fffffffffffff);
static constexpr uint64_t infinity = UINT64_C(0x7ff0000000000000);
static constexpr uint64_t canonical_nan = UINT64_C(0x7ff8000000000000);
static constexpr uint64_t one = UINT64_C(0x3ff0000000000000);

class Bench {
    VerilatedContext context_;
    VFP64FMA dut_{&context_};
    Reference reference_;
public:
    uint64_t checked = 0;
    uint64_t invalid_checked = 0;
    uint64_t host_checked = 0;
    std::array<uint64_t, 5> mode_counts{};
    std::array<uint64_t, 5> categories{};
    std::array<uint64_t, 3> subnormal_inputs{};
    uint64_t negative_zeros = 0;

    void check_mode(uint64_t a, uint64_t b, uint64_t c, unsigned mode) {
        const uint64_t expected = reference_(a, b, c, mode);
        if (mode == 0) {
            // 別系統のhost FMAともRNE結果を照合し、参照実装を交差検査する。
            const double host = std::fma(as_double(a), as_double(b), as_double(c));
            const uint64_t host_bits = std::isnan(host) ? canonical_nan : as_bits(host);
            if (host_bits != expected)
                throw std::runtime_error("host FMAとMPFRのRNE結果が不一致");
            ++host_checked;
        }
        dut_.a = a; dut_.b = b; dut_.c = c;
        dut_.rounding_mode = mode;
        dut_.eval();
        if (dut_.result != expected) {
            std::cerr << std::hex << std::setfill('0')
                      << "FAIL a=" << std::setw(16) << a << " b=" << std::setw(16) << b
                      << " c=" << std::setw(16) << c << " mode=" << mode
                      << " actual=" << std::setw(16) << dut_.result
                      << " expected=" << std::setw(16) << expected << std::dec << '\n';
            throw std::runtime_error("FMA結果がMPFR参照と不一致");
        }
        if (mode > 4) {
            ++invalid_checked;
            return;
        }
        const std::array<uint64_t, 3> inputs{a, b, c};
        for (unsigned i = 0; i < 3; ++i)
            subnormal_inputs[i] += (inputs[i] & infinity) == 0 && (inputs[i] & fraction_mask) != 0;
        ++checked;
        ++mode_counts[mode];
        const uint64_t value = expected & ~sign_bit;
        const unsigned category = value == 0 ? 0 : value < UINT64_C(0x0010000000000000) ? 1 :
                                  value < infinity ? 2 : value == infinity ? 3 : 4;
        ++categories[category];
        negative_zeros += expected == sign_bit;
    }

    void check(uint64_t a, uint64_t b, uint64_t c) {
        // 三入力を保持してモードだけを切り替え、組合せ出力を即時に照合する。
        for (unsigned mode = 0; mode <= 4; ++mode) check_mode(a, b, c, mode);
    }

    void known(uint64_t a, uint64_t b, uint64_t c, uint64_t expected) {
        if (reference_(a, b, c) != expected) throw std::runtime_error("既知値と独立参照が不一致");
        check(a, b, c);
    }

    void known_modes(uint64_t a, uint64_t b, uint64_t c, const std::array<uint64_t, 5>& expected) {
        for (unsigned mode = 0; mode <= 4; ++mode)
            if (reference_(a, b, c, mode) != expected[mode])
                throw std::runtime_error("モード別の既知値と独立参照が不一致: mode=" + std::to_string(mode));
        check(a, b, c);
    }
};

static uint64_t random_bits(uint64_t& state) {
    state ^= state << 13;
    state ^= state >> 7;
    state ^= state << 17;
    return state;
}

int main(int argc, char** argv) try {
    uint64_t random_count = 200000;
    bool sweep_exponents = false;
    for (int i = 1; i < argc; ++i) {
        std::string option = argv[i];
        if (option.rfind("--random=", 0) == 0) random_count = std::stoull(option.substr(9));
        else if (option == "--sweep-exponents") sweep_exponents = true;
        else throw std::runtime_error("不明な引数: " + option);
    }
    if (std::fesetround(FE_TONEAREST) != 0)
        throw std::runtime_error("host FMAのRNE設定に失敗した");
    Bench bench;
    const uint64_t half = UINT64_C(0x3fe0000000000000);
    const uint64_t two = UINT64_C(0x4000000000000000);
    const uint64_t min_normal = UINT64_C(0x0010000000000000);
    const uint64_t max_finite = infinity - 1;
    const uint64_t half_ulp_one = UINT64_C(0x3ca0000000000000); // 2^-53
    const uint64_t half_ulp_max = UINT64_C(0x7c90000000000000); // 2^970

    // 融合性、tie、overflow前の相殺、subnormal境界、符号付きzeroを参照側も検査。
    // (1+2^-52)*(1-2^-52)-1 = -2^-104。
    bench.known(one + 1, one - 2, one | sign_bit, UINT64_C(0xb970000000000000));
    bench.known(max_finite, two, max_finite | sign_bit, max_finite);
    bench.known(one, one, half_ulp_one, one);
    bench.known(one + 1, one, half_ulp_one, one + 2);
    bench.known(1, half, 0, 0);
    bench.known(sign_bit | 1, half, sign_bit, sign_bit);
    bench.known(3, half, 0, 2);
    bench.known(min_normal, one - 1, 0, min_normal);
    bench.known(one, one, one | sign_bit, 0);
    bench.known(sign_bit, one, sign_bit, sign_bit);
    bench.known(0, infinity, one, canonical_nan);
    bench.known(infinity, one, infinity | sign_bit, canonical_nan);

    // RNE・RTZ・RDN・RUP・RMMの順。tiny積、符号、tie、overflowの独立した既知値。
    bench.known_modes(1, 1, one, {one, one, one, one + 1, one});
    bench.known_modes(sign_bit | 1, 1, one, {one, one - 1, one - 1, one, one});
    bench.known_modes(1, 1, one | sign_bit,
        {one | sign_bit, (one - 1) | sign_bit, one | sign_bit, (one - 1) | sign_bit, one | sign_bit});
    bench.known_modes(sign_bit | 1, 1, one | sign_bit,
        {one | sign_bit, one | sign_bit, (one + 1) | sign_bit, one | sign_bit, one | sign_bit});
    bench.known_modes(sign_bit | 1, 1, 1, {1, 0, 0, 1, 1});
    bench.known_modes(one, one, one | sign_bit, {0, 0, sign_bit, 0, 0});
    bench.known_modes(sign_bit | 1, half, sign_bit,
        {sign_bit, sign_bit, sign_bit | 1, sign_bit, sign_bit | 1});
    bench.known_modes(max_finite, two, 0,
        {infinity, max_finite, max_finite, infinity, infinity});
    bench.known_modes(max_finite | sign_bit, two, 0,
        {infinity | sign_bit, max_finite | sign_bit, infinity | sign_bit, max_finite | sign_bit, infinity | sign_bit});
    bench.known_modes(one, one, half_ulp_one, {one, one, one, one + 1, one + 1});
    bench.known_modes(one | sign_bit, one, half_ulp_one | sign_bit,
        {one | sign_bit, one | sign_bit, (one + 1) | sign_bit, one | sign_bit, (one + 1) | sign_bit});
    bench.known_modes(max_finite, one, half_ulp_max,
        {infinity, max_finite, max_finite, infinity, infinity});
    bench.known_modes(max_finite | sign_bit, one, half_ulp_max | sign_bit,
        {infinity | sign_bit, max_finite | sign_bit, infinity | sign_bit, max_finite | sign_bit, infinity | sign_bit});

    const std::array<unsigned, 23> exponents{
        0, 1, 2, 3, 511, 512, 513, 969, 970, 971, 1021, 1022, 1023, 1024, 1025,
        1075, 1076, 1077, 1534, 1535, 1536, 2045, 2046
    };
    const auto selected = [&](unsigned exponent) {
        for (auto value : exponents) if (value == exponent) return true;
        return false;
    };
    // 相殺後の2の冪と両隣。全52位置を走査し、stressは全有限指数fieldを通す。
    for (unsigned exponent = 0; exponent <= 2046; ++exponent) {
        if (!sweep_exponents && !selected(exponent)) continue;
        const uint64_t base = uint64_t(exponent) << 52;
        for (unsigned bit = 0; bit < 52; ++bit) {
            for (int offset : {-1, 0, 1}) {
                const uint64_t value = base | ((UINT64_C(1) << bit) + offset);
                for (uint64_t multiplier : {one, one + 1}) {
                    bench.check(value, multiplier, base ^ sign_bit);
                    bench.check(value ^ sign_bit, multiplier, base);
                }
            }
        }
    }

    const std::array<uint64_t, 26> values{
        0, sign_bit, 1, sign_bit | 1, UINT64_C(0x0007ffffffffffff), UINT64_C(0x0008000000000000),
        fraction_mask, sign_bit | fraction_mask, min_normal, sign_bit | min_normal, min_normal + 1,
        half, one - 1, one, one | sign_bit, one + 1, two, two | sign_bit,
        max_finite, max_finite | sign_bit, infinity, infinity | sign_bit,
        canonical_nan, UINT64_C(0xfff8123456789abc), infinity + 1, UINT64_C(0xfff0000000012345)
    };
    for (auto a : values) for (auto b : values) for (auto c : values) {
        bench.check(a, b, c);
        for (unsigned mode = 5; mode <= 7; ++mode) bench.check_mode(a, b, c, mode);
    }
    std::cout << "PASS: directed=" << bench.checked << '\n';

    // Cの指数差で整列端、全桁消失、上位/下位境界、bypassの両側を検査する。
    const std::array<int, 24> deltas{
        -1076, -1075, -1074, -165, -164, -163, -109, -108, -107,
        -56, -55, -54, -53, -52, -1, 0, 1, 52, 53, 54, 55, 56, 57, 58
    };
    const std::array<unsigned, 11> sweep_anchors{0, 1, 2, 511, 512, 1022, 1023, 1024, 1534, 2045, 2046};
    for (unsigned ea = 0; ea <= 2046; ++ea) {
        if (!sweep_exponents && !selected(ea)) continue;
        for (auto eb : sweep_anchors) {
            const int ep = int(ea == 0 ? 1 : ea) + int(eb == 0 ? 1 : eb) - 1023;
            for (int delta : deltas) {
                const int ec = ep + delta;
                if (ec < 0 || ec > 2046) continue;
                for (uint64_t fraction : {UINT64_C(0), UINT64_C(1), fraction_mask}) {
                    const uint64_t a = (uint64_t(ea) << 52) | fraction;
                    const uint64_t b = (uint64_t(eb) << 52) | (fraction ^ fraction_mask);
                    const uint64_t c = (uint64_t(ec) << 52) | fraction;
                    bench.check(a, b, c);
                    bench.check(a, b, c ^ sign_bit);
                    bench.check(a ^ sign_bit, b, c);
                    bench.check(b, a, c ^ sign_bit);
                }
            }
        }
    }
    std::cout << "PASS: directed+exponent-boundaries=" << bench.checked << '\n';

    uint64_t state = UINT64_C(0xf64f0a0123456789);
    for (uint64_t i = 0; i < random_count; ++i) {
        uint64_t a = random_bits(state), b = random_bits(state), c = random_bits(state);
        switch (i % 8) {
        case 1: a &= sign_bit | fraction_mask; break;
        case 2: b &= sign_bit | fraction_mask; c &= sign_bit | fraction_mask; break;
        case 3: c = values[random_bits(state) % values.size()]; break;
        case 4:
            // host FMAで相殺しやすい入力を作る。合否判定は上記MPFRで行う。
            c = as_bits(std::fma(as_double(a), as_double(b), 0.0)) ^ sign_bit;
            c += i % 3 - 1;
            break;
        case 5: b = one; c = a ^ sign_bit; break;
        case 6: b = one + 1; c = a ^ sign_bit; break;
        case 7: c &= sign_bit | fraction_mask; break;
        default: break;
        }
        bench.check(a, b, c);
    }
    for (auto count : bench.categories) if (!count) throw std::runtime_error("出力分類の検証漏れ");
    for (auto count : bench.subnormal_inputs) if (!count) throw std::runtime_error("入力subnormalの検証漏れ");
    if (!bench.negative_zeros) throw std::runtime_error("負zeroの検証漏れ");
    for (auto count : bench.mode_counts)
        if (count * 5 != bench.checked) throw std::runtime_error("丸めモードの検証漏れ");
    if (bench.host_checked * 5 != bench.checked) throw std::runtime_error("host参照の検証漏れ");
    std::cout << "PASS: checked=" << bench.checked << " random=" << random_count
              << " sweep_exponents=" << sweep_exponents << " mpfr=" << mpfr_get_version() << '\n';
    std::cout << "MODES: RNE=" << bench.mode_counts[0] << " RTZ=" << bench.mode_counts[1]
              << " RDN=" << bench.mode_counts[2] << " RUP=" << bench.mode_counts[3]
              << " RMM=" << bench.mode_counts[4] << " invalid=" << bench.invalid_checked << '\n';
    std::cout << "OUTPUT: zero=" << bench.categories[0] << " subnormal=" << bench.categories[1]
              << " normal=" << bench.categories[2] << " inf=" << bench.categories[3]
              << " nan=" << bench.categories[4] << " negative_zero=" << bench.negative_zeros << '\n';
    std::cout << "INPUT_SUBNORMAL: a=" << bench.subnormal_inputs[0] << " b=" << bench.subnormal_inputs[1]
              << " c=" << bench.subnormal_inputs[2] << '\n';
    std::cout << "HOST_RNE: checked=" << bench.host_checked << '\n';
    return 0;
} catch (const std::exception& error) {
    std::cerr << "FAIL: " << error.what() << '\n';
    return 1;
}
