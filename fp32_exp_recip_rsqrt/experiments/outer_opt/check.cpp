// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0
// 同じ候補から生成したRTL比較topを、固定した入力格子で列挙する。
#include <array>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <memory>
#include <string_view>
#include <omp.h>
#include "verilated.h"
#ifdef KERNEL_CHECK
#include "VKernelCheck.h"
using Dut = VKernelCheck;
#else
#include "VFullCheck.h"
using Dut = VFullCheck;
#endif

static bool same(const Dut& d) {
    return d.baseline == d.centered && d.baseline == d.rounding && d.baseline == d.combined;
}

int main(int argc, char** argv) {
    const int threads = argc > 1 ? std::atoi(argv[1]) : 8;
    if (threads < 1 || threads > 64) return 2;
    omp_set_num_threads(threads);
    const bool full = argc > 2 && std::string_view(argv[2]) == "--full";
    std::uint64_t checked = 0, failures = 0;
    const double start = omp_get_wtime();
#pragma omp parallel reduction(+:checked,failures)
    {
        auto context = std::make_unique<VerilatedContext>();
        context->threads(1);
        auto dut = std::make_unique<Dut>(context.get());
#ifdef KERNEL_CHECK
#pragma omp for schedule(dynamic)
        for (int row = 0; row < 448; ++row) {
            const int bank = row < 64 ? 0 : 1+(row-64)/128;
            dut->bank = bank;
            dut->index = bank == 0 ? row : (row-64)%128;
            const int lo = bank == 0 ? -105264 : -65536;
            const int hi = bank == 0 ? 105264 : 65534;
            const int step = bank == 0 ? 1 : 2;
            for (int delta = lo; delta <= hi; delta += step) {
                dut->delta = static_cast<std::uint32_t>(delta)&0x3ffffu;
                dut->eval();
                ++checked;
                if (!same(*dut)) ++failures;
            }
        }
#else
        // expのactiveまたは全bit patternを1M入力単位へ分ける。
#pragma omp for schedule(dynamic)
        for (int block = 0; block < (full ? 4096 : 512); ++block) {
            dut->op = 1;
            const std::uint32_t first = full ? static_cast<std::uint32_t>(block) << 20
                : ((block >= 256 ? 1u : 0u) << 31)
                  | ((102u << 23)+((static_cast<std::uint32_t>(block)&255u) << 20));
            for (std::uint32_t j = 0; j < (1u << 20); ++j) {
                dut->x = first+j;
                dut->eval();
                ++checked;
                if (!same(*dut)) ++failures;
            }
        }
        // 逆数の両符号、逆平方根の指数偶奇、負入力を全仮数で比較する。
#pragma omp for schedule(dynamic)
        for (int block = 0; block < 48; ++block) {
            const int group = block/8;
            dut->op = group < 2 ? 2 : 4;
            const std::uint32_t sign = (group < 2 ? group : (group-2)/2);
            const std::uint32_t exponent = group < 2 ? 127u : 127u+((group-2)&1);
            const std::uint32_t first = (sign << 31)|(exponent << 23)|((block&7) << 20);
            for (std::uint32_t j = 0; j < (1u << 20); ++j) {
                dut->x = first+j;
                dut->eval();
                ++checked;
                if (!same(*dut)) ++failures;
            }
        }
        // 全指数端点は無効op、NaN、Inf、zero、subnormalを含む。
#pragma omp for schedule(dynamic)
        for (int tag = 0; tag < 4096; ++tag) {
            dut->op = tag/512;
            for (std::uint32_t fraction : {0u, 1u, 0x3fffffu, 0x400000u, 0x7ffffeu, 0x7fffffu}) {
                dut->x = (static_cast<std::uint32_t>(tag&511) << 23)|fraction;
                dut->eval();
                ++checked;
                if (!same(*dut)) ++failures;
            }
        }
#pragma omp for schedule(static)
        for (int op = 0; op < 8; ++op) {
            std::uint32_t random = 0x6f757465u+op;
            dut->op = op;
            for (int j = 0; j < 200000; ++j) {
                random ^= random << 13;
                random ^= random >> 17;
                random ^= random << 5;
                dut->x = random;
                dut->eval();
                ++checked;
                if (!same(*dut)) ++failures;
            }
        }
#endif
    }
#ifdef KERNEL_CHECK
    constexpr std::uint64_t expected = 38639680;
#else
    const std::uint64_t expected = (full ? (1ull << 32) : 536870912ull)+50331648+24576+1600000;
#endif
    if (checked != expected) return 3;
    std::cout << (failures ? "FAIL" : "PASS") << ": inputs=" << checked
              << " candidates=3 mismatches=" << failures << " threads=" << threads
              << " seconds=" << omp_get_wtime()-start << std::endl;
    return failures ? 1 : 0;
}
