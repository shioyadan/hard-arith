// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0

#include "VFP32ElementaryConfigs.h"
#include "verilated.h"

#include <array>
#include <bit>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <iostream>

extern "C" std::uint32_t fp32_elementary_test_input(
    std::uint32_t function_index, std::uint32_t ordinal);

int main(int argc, char** argv) {
    VerilatedContext context;
    context.commandArgs(argc, argv);
    VFP32ElementaryConfigs dut{&context};
    constexpr std::uint32_t qnan = 0x7fc00000u;
    constexpr unsigned random_cycles = 20000;
    std::uint64_t vectors = 0;
    std::array<std::uint64_t, 64> enabled_checks{}, disabled_checks{}, invalid_checks{};

    const auto check = [&](std::uint32_t x, unsigned op) {
        dut.x = x;
        dut.op = op;
        dut.eval();
        ++vectors;
        const bool valid = op != 0 && (op & (op - 1)) == 0;
        // sinpi/cospiを同じ設定bitへ対応させ、opの妥当性は別に判定する。
        const unsigned group = op >= 32 ? 32 : op;
        if (!valid && dut.default_result != qnan) {
            std::cerr << "FAIL: default invalid op=" << op << '\n';
            std::exit(1);
        }
        for (unsigned config = 0; config < 64; ++config) {
            const bool enabled = valid && (config & group) != 0;
            const auto expected = enabled ? dut.default_result : qnan;
            if (dut.results[config] != expected) {
                std::cerr << "FAIL: config=" << config << " op=" << op
                          << std::hex << " x=" << x
                          << " actual=" << dut.results[config]
                          << " expected=" << expected << '\n';
                std::exit(1);
            }
            if (!valid) ++invalid_checks[config];
            else if (enabled) ++enabled_checks[config];
            else ++disabled_checks[config];
        }
    };

    // 符号付きzero、subnormal端点、normal端点、Inf、quiet/signaling NaN、
    // 定義域外とexp2の飽和境界を全128 opと組み合わせる。
    constexpr std::array<std::uint32_t, 32> directed = {
        0x00000000, 0x80000000, 0x00000001, 0x80000001,
        0x007fffff, 0x807fffff, 0x00800000, 0x80800000,
        0x7f7fffff, 0xff7fffff, 0x7f800000, 0xff800000,
        0x7fc00000, 0xffc00001, 0x7f800001, 0xff800001,
        0x3e800000, 0xbe800000, 0x3f000000, 0xbf000000,
        0x3f7fffff, 0x3f800000, 0x3f800001, 0xbf800000,
        0x40000000, 0xc0000000, 0x42ffffff, 0x43000000,
        0xc2fbffff, 0xc2fc0000, 0xc2fc0001, 0xc3000000
    };
    for (const auto x : directed)
        for (unsigned op = 0; op < 128; ++op) check(x, op);

    // 既存数値testと同じ固定seed・関数別の入力分布。無効opも乱数入力で調べる。
    for (unsigned fn = 0; fn < 7; ++fn)
        for (unsigned i = 0; i < random_cycles; ++i)
            check(fp32_elementary_test_input(fn, i), 1u << fn);
    for (unsigned op = 0; op < 128; ++op)
        for (unsigned i = 0; i < 32; ++i)
            check(fp32_elementary_test_input(i % 7, 20000 + i), op);

    // 全指数・正負・128区分の境界直前／境界／直後。64区分境界も含む。
    // bit patternの端では範囲外の隣接値を作らない。
    for (unsigned sign = 0; sign < 2; ++sign)
        for (unsigned exponent = 0; exponent < 256; ++exponent)
            for (unsigned row = 0; row < 128; ++row) {
                const std::uint32_t magnitude = (exponent << 23) | (row << 16);
                for (int offset = -1; offset <= 1; ++offset) {
                    const std::int64_t neighbor = std::int64_t(magnitude) + offset;
                    if (neighbor < 0 || neighbor > 0x7fffffffu) continue;
                    for (unsigned fn = 0; fn < 7; ++fn)
                        check((sign << 31) | std::uint32_t(neighbor), 1u << fn);
                }
            }

    // exp2のn/64と半区間境界、sin/cosの位相区分・零点・極値の近傍。
    // ここでの2のべき乗による除算はbinary32で厳密に表現できる。
    for (int n = -16384; n <= 16384; ++n) {
        const auto bits = std::bit_cast<std::uint32_t>(float(n) / 128.0f);
        for (int offset = -1; offset <= 1; ++offset) {
            if (bits == 0 && offset < 0) continue;
            const auto x = std::uint32_t(std::int64_t(bits) + offset);
            check(x, 1);
            if (n >= -256 && n <= 256) {
                check(x, 32);
                check(x, 64);
            }
        }
    }

    for (unsigned config = 0; config < 64; ++config)
        std::cout << "CONFIG: mask=" << config
                  << " enabled=" << enabled_checks[config]
                  << " disabled=" << disabled_checks[config]
                  << " invalid=" << invalid_checks[config] << '\n';
    std::cout << "PASS: configs=64 vectors=" << vectors
              << " comparisons=" << vectors * 64
              << " random_per_function=" << random_cycles << '\n';
    dut.final();
}
