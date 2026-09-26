// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0
#include "VFP32FMA.h"
#include "verilated.h"
#include "reference.hpp"
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>

class Bench {
    VerilatedContext context_;
    VFP32FMA dut_{&context_};
    Reference reference_;
public:
    uint64_t checked = 0;
    uint64_t invalid_checked = 0;
    std::array<uint64_t, 5> mode_counts{};
    std::array<uint64_t, 5> categories{};
    std::array<uint64_t, 3> subnormal_inputs{};
    uint64_t negative_zeros = 0;

    void check_mode(uint32_t a, uint32_t b, uint32_t c, unsigned mode) {
        const uint32_t expected = reference_(a, b, c, mode);
        dut_.a = a; dut_.b = b; dut_.c = c;
        dut_.rounding_mode = mode;
        dut_.eval();
        if (dut_.result != expected) {
            std::cerr << std::hex << std::setfill('0')
                      << "FAIL a=" << std::setw(8) << a << " b=" << std::setw(8) << b
                      << " c=" << std::setw(8) << c << " mode=" << mode
                      << " actual=" << std::setw(8) << dut_.result
                      << " expected=" << std::setw(8) << expected << std::dec << '\n';
            throw std::runtime_error("FMA結果がMPFR参照と不一致");
        }
        if (mode > 4) {
            ++invalid_checked;
            return;
        }
        const std::array<uint32_t, 3> inputs{a, b, c};
        for (unsigned i = 0; i < 3; ++i)
            subnormal_inputs[i] += (inputs[i] & 0x7f800000) == 0 && (inputs[i] & 0x007fffff) != 0;
        ++checked;
        ++mode_counts[mode];
        const uint32_t value = expected & 0x7fffffff;
        const unsigned category = value == 0 ? 0 : value < 0x00800000 ? 1 :
                                  value < 0x7f800000 ? 2 : value == 0x7f800000 ? 3 : 4;
        ++categories[category];
        negative_zeros += expected == 0x80000000;
    }

    void check(uint32_t a, uint32_t b, uint32_t c) {
        // 三入力を変えずにモードだけを切り替えて、組合せ出力を照合する。
        for (unsigned mode = 0; mode <= 4; ++mode) check_mode(a, b, c, mode);
    }

    void known(uint32_t a, uint32_t b, uint32_t c, uint32_t expected) {
        if (reference_(a, b, c) != expected) throw std::runtime_error("既知値と独立参照が不一致");
        check(a, b, c);
    }

    void known_modes(uint32_t a, uint32_t b, uint32_t c, const std::array<uint32_t, 5>& expected) {
        for (unsigned mode = 0; mode <= 4; ++mode)
            if (reference_(a, b, c, mode) != expected[mode])
                throw std::runtime_error("モード別の既知値と独立参照が不一致: mode=" + std::to_string(mode));
        check(a, b, c);
    }
};

static uint32_t random_bits(uint32_t& state) {
    state ^= state << 13;
    state ^= state >> 17;
    state ^= state << 5;
    return state;
}

int main(int argc, char** argv) try {
    uint64_t random_count = 200000;
    bool all_exponents = false;
    for (int i = 1; i < argc; ++i) {
        std::string option = argv[i];
        if (option.rfind("--random=", 0) == 0) random_count = std::stoull(option.substr(9));
        else if (option == "--all-exponents") all_exponents = true;
        else throw std::runtime_error("不明な引数: " + option);
    }
    Bench bench;

    // 融合性、tie、overflow前の相殺、subnormal境界、符号付きzeroを参照側も検査。
    bench.known(0x3f800001, 0x3f7ffffe, 0xbf800000, 0xa8800000);
    bench.known(0x7f7fffff, 0x40000000, 0xff7fffff, 0x7f7fffff);
    bench.known(0x3f800000, 0x3f800000, 0x33800000, 0x3f800000);
    bench.known(0x3f800001, 0x3f800000, 0x33800000, 0x3f800002);
    bench.known(0x00000001, 0x3f000000, 0x00000000, 0x00000000);
    bench.known(0x80000001, 0x3f000000, 0x80000000, 0x80000000);
    bench.known(0x00000003, 0x3f000000, 0x00000000, 0x00000002);
    bench.known(0x00800000, 0x3f7fffff, 0x00000000, 0x00800000);
    bench.known(0x3f800000, 0x3f800000, 0xbf800000, 0x00000000);
    bench.known(0x80000000, 0x3f800000, 0x80000000, 0x80000000);
    bench.known(0x00000000, 0x7f800000, 0x3f800000, 0x7fc00000);
    bench.known(0x7f800000, 0x3f800000, 0xff800000, 0x7fc00000);

    // RNE・RTZ・RDN・RUP・RMMの順。微小な積、符号、tie、overflowを独立に固定する。
    bench.known_modes(1, 1, 0x3f800000,
        {0x3f800000, 0x3f800000, 0x3f800000, 0x3f800001, 0x3f800000});
    bench.known_modes(0x80000001, 1, 0x3f800000,
        {0x3f800000, 0x3f7fffff, 0x3f7fffff, 0x3f800000, 0x3f800000});
    bench.known_modes(1, 1, 0xbf800000,
        {0xbf800000, 0xbf7fffff, 0xbf800000, 0xbf7fffff, 0xbf800000});
    bench.known_modes(0x80000001, 1, 0xbf800000,
        {0xbf800000, 0xbf800000, 0xbf800001, 0xbf800000, 0xbf800000});
    bench.known_modes(0x80000001, 1, 1, {1, 0, 0, 1, 1});
    bench.known_modes(0x3f800000, 0x3f800000, 0xbf800000, {0, 0, 0x80000000, 0, 0});
    bench.known_modes(0x80000001, 0x3f000000, 0x80000000,
        {0x80000000, 0x80000000, 0x80000001, 0x80000000, 0x80000001});
    bench.known_modes(0x7f7fffff, 0x40000000, 0,
        {0x7f800000, 0x7f7fffff, 0x7f7fffff, 0x7f800000, 0x7f800000});
    bench.known_modes(0xff7fffff, 0x40000000, 0,
        {0xff800000, 0xff7fffff, 0xff800000, 0xff7fffff, 0xff800000});
    bench.known_modes(0x3f800000, 0x3f800000, 0x33800000,
        {0x3f800000, 0x3f800000, 0x3f800000, 0x3f800001, 0x3f800001});
    bench.known_modes(0xbf800000, 0x3f800000, 0xb3800000,
        {0xbf800000, 0xbf800000, 0xbf800001, 0xbf800000, 0xbf800001});
    bench.known_modes(0x7f7fffff, 0x3f800000, 0x73000000,
        {0x7f800000, 0x7f7fffff, 0x7f7fffff, 0x7f800000, 0x7f800000});
    bench.known_modes(0xff7fffff, 0x3f800000, 0xf3000000,
        {0xff800000, 0xff7fffff, 0xff800000, 0xff7fffff, 0xff800000});

    // 相殺後の2の冪とその両隣。負値の絶対値化と丸めの統合では、
    // |sum|-1の先頭位置が一つ下がる境界と、捨てる桁のall-oneを検査する。
    // 積の符号も反転し、全有限指数と仮数内の全bit位置を5モードで通す。
    for (uint32_t exponent = 0; exponent <= 254; ++exponent) {
        const uint32_t base = exponent << 23;
        for (unsigned bit = 0; bit < 23; ++bit) {
            for (int offset : {-1, 0, 1}) {
                const uint32_t value = base | uint32_t((1 << bit) + offset);
                for (uint32_t multiplier : {0x3f800000u, 0x3f800001u}) {
                    bench.check(value, multiplier, base ^ 0x80000000u);
                    bench.check(value ^ 0x80000000u, multiplier, base);
                }
            }
        }
    }

    const std::array<uint32_t, 26> values{
        0, 0x80000000, 1, 0x80000001, 0x003fffff, 0x00400000, 0x007fffff, 0x807fffff,
        0x00800000, 0x80800000, 0x00800001, 0x3f000000, 0x3f7fffff, 0x3f800000,
        0xbf800000, 0x3f800001, 0x40000000, 0xc0000000, 0x7f7fffff, 0xff7fffff,
        0x7f800000, 0xff800000, 0x7fc00000, 0xffc12345, 0x7f800001, 0xff812345
    };
    for (auto a : values) for (auto b : values) for (auto c : values) {
        bench.check(a, b, c);
        for (unsigned mode = 5; mode <= 7; ++mode) bench.check_mode(a, b, c, mode);
    }
    std::cout << "PASS: directed=" << bench.checked << '\n';

    // 加数と積の指数差を変え、桁合わせの範囲端と相殺を通す。
    const std::array<unsigned, 11> exponents{0, 1, 2, 63, 64, 126, 127, 128, 190, 253, 254};
    const std::array<int, 16> deltas{-151, -76, -50, -27, -26, -25, -24, -1, 0, 1, 23, 24, 25, 26, 27, 28};
    for (unsigned ea = 0; ea <= 254; ++ea) {
        for (unsigned eb = 0; eb <= 254; ++eb) {
            if (!all_exponents) {
                bool selected = false;
                for (auto e : exponents) selected |= eb == e;
                if (!selected) continue;
            }
            const int ep = int(ea == 0 ? 1 : ea) + int(eb == 0 ? 1 : eb) - 127;
            for (int delta : deltas) {
                const int ec = ep + delta;
                if (ec < 0 || ec > 254) continue;
                for (uint32_t fraction : {0u, 1u, 0x007fffffu}) {
                    const uint32_t a = (ea << 23) | fraction;
                    const uint32_t b = (eb << 23) | (fraction ^ 0x007fffffu);
                    const uint32_t c = (uint32_t(ec) << 23) | fraction;
                    bench.check(a, b, c);
                    bench.check(a, b, c ^ 0x80000000u);
                    bench.check(a ^ 0x80000000u, b, c);
                }
            }
        }
    }
    std::cout << "PASS: directed+exponent-boundaries=" << bench.checked << '\n';

    uint32_t state = 0xf32f0a01;
    for (uint64_t i = 0; i < random_count; ++i) {
        uint32_t a = random_bits(state), b = random_bits(state), c = random_bits(state);
        switch (i % 8) {
        case 1: a &= 0x807fffff; break;
        case 2: b &= 0x807fffff; c &= 0x807fffff; break;
        case 3: c = values[random_bits(state) % values.size()]; break;
        case 4:
            // host FMAは相殺しやすい入力の生成だけに使い、判定はMPFRで行う。
            c = as_bits(std::fma(as_float(a), as_float(b), 0.0f)) ^ 0x80000000u;
            c += uint32_t(i % 3) - 1u;
            break;
        case 5: b = 0x3f800000; c = a ^ 0x80000000u; break;
        case 6: b = 0x3f800001; c = a ^ 0x80000000u; break;
        case 7: c &= 0x807fffff; break;
        default: break;
        }
        bench.check(a, b, c);
    }
    for (auto count : bench.categories) if (!count) throw std::runtime_error("出力分類の検証漏れ");
    for (auto count : bench.subnormal_inputs) if (!count) throw std::runtime_error("入力subnormalの検証漏れ");
    if (!bench.negative_zeros) throw std::runtime_error("負zeroの検証漏れ");
    for (auto count : bench.mode_counts)
        if (count * 5 != bench.checked) throw std::runtime_error("丸めモードの検証漏れ");
    std::cout << "PASS: checked=" << bench.checked << " random=" << random_count
              << " all_exponents=" << all_exponents << " mpfr=" << mpfr_get_version() << '\n';
    std::cout << "MODES: RNE=" << bench.mode_counts[0] << " RTZ=" << bench.mode_counts[1]
              << " RDN=" << bench.mode_counts[2] << " RUP=" << bench.mode_counts[3]
              << " RMM=" << bench.mode_counts[4] << " invalid=" << bench.invalid_checked << '\n';
    std::cout << "OUTPUT: zero=" << bench.categories[0] << " subnormal=" << bench.categories[1]
              << " normal=" << bench.categories[2] << " inf=" << bench.categories[3]
              << " nan=" << bench.categories[4] << " negative_zero=" << bench.negative_zeros << '\n';
    std::cout << "INPUT_SUBNORMAL: a=" << bench.subnormal_inputs[0] << " b=" << bench.subnormal_inputs[1]
              << " c=" << bench.subnormal_inputs[2] << '\n';
    return 0;
} catch (const std::exception& error) {
    std::cerr << "FAIL: " << error.what() << '\n';
    return 1;
}
