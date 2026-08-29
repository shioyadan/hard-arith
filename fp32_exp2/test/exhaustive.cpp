// Copyright 2026 Ryota Shioya and Toru Koizumi
// SPDX-License-Identifier: Apache-2.0

// FP32Expの共通全数検査器を、2^xのoracleと33指数field範囲へ設定する。
#define FP32_EXP_ACTIVE_EXPONENT_COUNT 33u
#define FP32_EXP_STD_FUNCTION std::exp2
#define FP32_EXP_MPFR_FUNCTION mpfr_exp2
#define FP32_EXP_ORACLE_NAME "std::exp2"
#include "../../fp32_exp/test/exhaustive.cpp"
