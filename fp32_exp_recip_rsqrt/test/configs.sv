// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0

// 二設定へ同じ入力を与え、設定の取り違えと通常経路の変化も検査する。
module FP32ExpRecipRsqrtConfigs(
    input wire [31:0] x,
    input wire [2:0] op,
    output wire [31:0] ftz,
    output wire [31:0] gradual
`ifdef COMPARE_BASELINE
    , output wire [31:0] baseline
`endif
);
    FP32ExpRecipRsqrt #(.SUPPORT_SUBNORMAL(1'b0)) dut_ftz(.x(x), .op(op), .result(ftz));
    FP32ExpRecipRsqrt #(.SUPPORT_SUBNORMAL(1'b1)) dut_gradual(.x(x), .op(op), .result(gradual));
`ifdef COMPARE_BASELINE
    FP32ExpRecipRsqrtBaseline dut_baseline(.x(x), .op(op), .result(baseline));
`endif
endmodule
