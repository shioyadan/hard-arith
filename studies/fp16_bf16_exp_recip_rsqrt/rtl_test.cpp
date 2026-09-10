// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0
// 全x・opで形式を交互に切り替え、有効opは整数モデル、無効opはqNaNと照合する。
#include "VFP16BF16ExpRecipRsqrtStudy.h"
#include <cstdint>
#include <cstdio>
#include <vector>

static_assert(FORMAT_MODE >= 0 && FORMAT_MODE <= 2, "unsupported FORMAT_MODE");
static_assert(SUPPORT_SUBNORMAL == 0 || SUPPORT_SUBNORMAL == 1, "unsupported SUPPORT_SUBNORMAL");

static bool read_vectors(const char *path, std::vector<uint16_t> &values) {
    FILE *input = std::fopen(path, "rb");
    if (!input) return false;
    for (auto &value : values) {
        unsigned char bytes[2];
        if (std::fread(bytes, 1, 2, input) != 2) {
            std::fclose(input);
            return false;
        }
        value = bytes[0] | (unsigned(bytes[1]) << 8);
    }
    const bool complete = std::fgetc(input) == EOF;
    const bool closed = std::fclose(input) == 0;
    return complete && closed;
}

int main(int argc, char **argv) {
    if (argc != 3) return 2;
    std::vector<uint16_t> expected[2] = {std::vector<uint16_t>(3*65536), std::vector<uint16_t>(3*65536)};
    if (!read_vectors(argv[1], expected[0]) || !read_vectors(argv[2], expected[1])) return 2;
    VFP16BF16ExpRecipRsqrtStudy dut;
    for (unsigned x = 0; x < 65536; ++x) {
        dut.x = x;
        for (unsigned op = 0; op < 8; ++op) {
            dut.op = op;
            const unsigned oi = op == 1 ? 0 : op == 2 ? 1 : 2;
            const bool legal = op == 1 || op == 2 || op == 4;
            for (unsigned format = 0; format < 2; ++format) {
                dut.is_bf16 = format;
                const unsigned selected = FORMAT_MODE == 0 ? format : FORMAT_MODE - 1;
                const unsigned model = legal ? expected[selected][oi*65536+x] : selected ? 0x7fc0 : 0x7e00;
                dut.eval();
                if (dut.result != model) {
                    std::printf("FAIL: bf16=%u op=%u x=%04x result=%04x model=%04x\n",
                                format, op, x, dut.result, model);
                    return 1;
                }
            }
        }
    }
    std::puts("PASS: legal=393216 invalid=655360 total=1048576 bit-exact vectors; format alternates every evaluation");
    std::printf("FORMAT_MODE=%d: is_bf16 input %s\n", FORMAT_MODE, FORMAT_MODE ? "ignored" : "selected");
    std::printf("SUPPORT_SUBNORMAL=%d\n", SUPPORT_SUBNORMAL);
}
