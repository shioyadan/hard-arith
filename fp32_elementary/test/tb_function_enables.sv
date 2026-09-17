// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0

// 全64設定を同じ入力で比較する。既定値のinstanceも別に置く。
module FP32ElementaryConfigs (
    input wire [31:0] x,
    input wire [6:0] op,
    output wire [31:0] default_result,
    output wire [31:0] results [0:63]
);
    FP32Elementary default_dut (.x(x), .op(op), .result(default_result));

    for (genvar config_index = 0; config_index < 64; config_index++) begin : configs
        FP32Elementary #(
            .ENABLE_EXP2(config_index[0]),
            .ENABLE_RECIP(config_index[1]),
            .ENABLE_RSQRT(config_index[2]),
            .ENABLE_SQRT(config_index[3]),
            .ENABLE_LOG2(config_index[4]),
            .ENABLE_SINCOS(config_index[5])
        ) dut (.x(x), .op(op), .result(results[config_index]));
    end
endmodule
