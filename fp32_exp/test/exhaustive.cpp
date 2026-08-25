// Copyright 2026 Ryota Shioya
// SPDX-License-Identifier: Apache-2.0

#include <chrono>      // shardごとの実行時間を測る。
#include <cstdint>     // 固定幅整数でbinary32 bit patternを扱う。
#include <cstdlib>     // コマンドライン整数を変換する。
#include <fstream>     // shard結果をJSONへ保存する。
#include <iomanip>     // JSON内の浮動小数表示精度を固定する。
#include <iostream>    // 引数エラーを表示する。

#include "VFP32Exp.h" // Verilatorが生成したFP32 expのモデルを使う。
#include "verilated.h"            // Verilatorモデルの実行環境を使う。

extern "C" uint64_t fp32_exp_ref_and_faithful_bounds(
    uint32_t input, uint32_t *reference,
    uint32_t *ambiguous); // 1回のexpqでFTZ参照値、faithful上下限、曖昧性を得る。

namespace {

constexpr uint64_t kMagnitudeCount = UINT64_C(1) << 28; // 32指数×2^23仮数の片符号分。
constexpr uint64_t kTotalCount = UINT64_C(1) << 29;     // 2符号を含む全検査入力数。
constexpr uint32_t kFractionMask = UINT32_C(0x007fffff); // binary32仮数fieldのmask。
constexpr uint32_t kPositiveInfinity = UINT32_C(0x7f800000); // exp(x)の+Inf bit pattern。

uint32_t input_from_ordinal(uint64_t ordinal)
{
    uint64_t magnitude_rank;                              // 符号を除いた昇順位置を得る。
    uint32_t sign;                                        // binary32の符号bitを作る。

    if (ordinal < kMagnitudeCount) {                      // 前半は負入力を数値の昇順に並べる。
        magnitude_rank = kMagnitudeCount - 1 - ordinal;   // 大きい絶対値から小さい絶対値へ進める。
        sign = UINT32_C(0x80000000);                      // 負号を付ける。
    } else {                                              // 後半は正入力を数値の昇順に並べる。
        magnitude_rank = ordinal - kMagnitudeCount;       // 小さい絶対値から大きい絶対値へ進める。
        sign = 0;                                         // 正号を付ける。
    }
    const uint32_t exponent = 102u +                      // 近似回路を使う最小指数fieldから始める。
        static_cast<uint32_t>(magnitude_rank >> 23);      // 32個の指数fieldを選ぶ。
    const uint32_t fraction = static_cast<uint32_t>(magnitude_rank) &
        kFractionMask;                                    // 各指数で2^23仮数を全列挙する。
    return sign | (exponent << 23) | fraction;             // binary32入力bit patternを組み立てる。
}

uint32_t ulp_distance(uint32_t actual, uint32_t reference)
{
    return actual >= reference ? actual - reference : reference - actual; // 非負出力のbit距離を返す。
}

struct Statistics {
    uint64_t total = 0;                                   // shardで検査した全入力数。
    uint64_t reference_zero = 0;                          // FTZ参照値が0の入力数。
    uint64_t reference_infinity = 0;                      // 参照値が+Infの入力数。
    uint64_t reference_finite = 0;                        // 参照値が非0有限normalの対象入力数。
    uint64_t actual_zero = 0;                             // RTL出力が0の入力数。
    uint64_t actual_infinity = 0;                         // RTL出力が+Infの入力数。
    uint64_t correct = 0;                                 // 全範囲でcorrect参照と一致した数。
    uint64_t one_ulp = 0;                                 // 全範囲で1 ULP異なった数。
    uint64_t over_one_ulp = 0;                            // 全範囲で1 ULPを超えた数。
    uint64_t finite_correct = 0;                          // 非0有限範囲でcorrect参照と一致した数。
    uint64_t finite_one_ulp = 0;                          // 非0有限範囲で1 ULP異なった数。
    uint64_t finite_over_one_ulp = 0;                     // 非0有限範囲で1 ULPを超えた数。
    uint64_t faithful_valid = 0;                          // 非0有限範囲でfaithfulだった数。
    uint64_t faithful_alternative = 0;                    // correctでないがfaithfulだった数。
    uint64_t faithful_violation = 0;                      // faithful上下限から外れた数。
    uint64_t faithful_below = 0;                          // faithful下限より小さかった数。
    uint64_t faithful_above = 0;                          // faithful上限より大きかった数。
    uint64_t faithful_ambiguous = 0;                      // binary128だけでは上下を確定できない数。
    uint64_t monotonic_violation = 0;                     // shard内部で出力が減少した数。
    uint32_t max_ulp = 0;                                 // 全範囲の最大ULP誤差。
    uint32_t max_finite_ulp = 0;                          // 非0有限範囲の最大ULP誤差。
    uint32_t worst_input = 0;                             // 全範囲最大ULPの入力。
    uint32_t worst_actual = 0;                            // 全範囲最大ULPのRTL出力。
    uint32_t worst_reference = 0;                         // 全範囲最大ULPのcorrect参照値。
    uint32_t worst_finite_input = 0;                      // 非0有限範囲最大ULPの入力。
    uint32_t worst_finite_actual = 0;                     // 非0有限範囲最大ULPのRTL出力。
    uint32_t worst_finite_reference = 0;                  // 非0有限範囲最大ULPのcorrect参照値。
    uint64_t first_faithful_ordinal = UINT64_MAX;         // 最初のfaithful違反位置。
    uint32_t first_faithful_input = 0;                    // 最初のfaithful違反入力。
    uint32_t first_faithful_actual = 0;                   // 最初のfaithful違反RTL出力。
    uint32_t first_faithful_lower = 0;                    // 最初のfaithful違反下限。
    uint32_t first_faithful_upper = 0;                    // 最初のfaithful違反上限。
    uint64_t first_monotonic_ordinal = UINT64_MAX;        // 最初の単調性違反位置。
    uint32_t first_monotonic_previous_input = 0;          // 単調性違反直前の入力。
    uint32_t first_monotonic_previous_actual = 0;         // 単調性違反直前の出力。
    uint32_t first_monotonic_input = 0;                   // 単調性違反を起こした入力。
    uint32_t first_monotonic_actual = 0;                  // 単調性違反を起こした出力。
};

void write_json(const char *path, uint64_t start, uint64_t end,
                uint32_t first_input, uint32_t first_actual,
                uint32_t last_input, uint32_t last_actual,
                double elapsed_seconds, const Statistics &s)
{
    std::ofstream out(path);                              // shard専用結果fileを開く。
    if (!out) {                                           // 保存先を開けなければ検査結果を失わず停止する。
        std::cerr << "結果を書けません: " << path << '\n';
        std::exit(2);
    }
    out << std::setprecision(12);                         // throughput再計算に十分な桁を残す。
    out << "{\n";                                       // Pythonが読むJSON objectを開始する。
    out << "  \"start\": " << start << ",\n";
    out << "  \"end\": " << end << ",\n";
    out << "  \"first_input\": " << first_input << ",\n";
    out << "  \"first_actual\": " << first_actual << ",\n";
    out << "  \"last_input\": " << last_input << ",\n";
    out << "  \"last_actual\": " << last_actual << ",\n";
    out << "  \"total\": " << s.total << ",\n";
    out << "  \"reference_zero\": " << s.reference_zero << ",\n";
    out << "  \"reference_infinity\": " << s.reference_infinity << ",\n";
    out << "  \"reference_finite\": " << s.reference_finite << ",\n";
    out << "  \"actual_zero\": " << s.actual_zero << ",\n";
    out << "  \"actual_infinity\": " << s.actual_infinity << ",\n";
    out << "  \"correct\": " << s.correct << ",\n";
    out << "  \"one_ulp\": " << s.one_ulp << ",\n";
    out << "  \"over_one_ulp\": " << s.over_one_ulp << ",\n";
    out << "  \"finite_correct\": " << s.finite_correct << ",\n";
    out << "  \"finite_one_ulp\": " << s.finite_one_ulp << ",\n";
    out << "  \"finite_over_one_ulp\": " << s.finite_over_one_ulp << ",\n";
    out << "  \"faithful_valid\": " << s.faithful_valid << ",\n";
    out << "  \"faithful_alternative\": " << s.faithful_alternative << ",\n";
    out << "  \"faithful_violation\": " << s.faithful_violation << ",\n";
    out << "  \"faithful_below\": " << s.faithful_below << ",\n";
    out << "  \"faithful_above\": " << s.faithful_above << ",\n";
    out << "  \"faithful_ambiguous\": " << s.faithful_ambiguous << ",\n";
    out << "  \"monotonic_violation\": " << s.monotonic_violation << ",\n";
    out << "  \"max_ulp\": " << s.max_ulp << ",\n";
    out << "  \"max_finite_ulp\": " << s.max_finite_ulp << ",\n";
    out << "  \"worst_input\": " << s.worst_input << ",\n";
    out << "  \"worst_actual\": " << s.worst_actual << ",\n";
    out << "  \"worst_reference\": " << s.worst_reference << ",\n";
    out << "  \"worst_finite_input\": " << s.worst_finite_input << ",\n";
    out << "  \"worst_finite_actual\": " << s.worst_finite_actual << ",\n";
    out << "  \"worst_finite_reference\": " << s.worst_finite_reference << ",\n";
    out << "  \"first_faithful_ordinal\": " << s.first_faithful_ordinal << ",\n";
    out << "  \"first_faithful_input\": " << s.first_faithful_input << ",\n";
    out << "  \"first_faithful_actual\": " << s.first_faithful_actual << ",\n";
    out << "  \"first_faithful_lower\": " << s.first_faithful_lower << ",\n";
    out << "  \"first_faithful_upper\": " << s.first_faithful_upper << ",\n";
    out << "  \"first_monotonic_ordinal\": " << s.first_monotonic_ordinal << ",\n";
    out << "  \"first_monotonic_previous_input\": " << s.first_monotonic_previous_input << ",\n";
    out << "  \"first_monotonic_previous_actual\": " << s.first_monotonic_previous_actual << ",\n";
    out << "  \"first_monotonic_input\": " << s.first_monotonic_input << ",\n";
    out << "  \"first_monotonic_actual\": " << s.first_monotonic_actual << ",\n";
    out << "  \"elapsed_seconds\": " << elapsed_seconds << "\n";
    out << "}\n";                                        // JSON objectを閉じる。
}

} // namespace

int main(int argc, char **argv)
{
    if (argc != 4) {                                      // start、end、出力先を必須にする。
        std::cerr << "usage: " << argv[0] << " START END OUTPUT_JSON\n";
        return 2;
    }
    const uint64_t start = std::strtoull(argv[1], nullptr, 0); // shard先頭ordinalを読む。
    const uint64_t end = std::strtoull(argv[2], nullptr, 0);   // shard終端ordinalを読む。
    if (start >= end || end > kTotalCount) {              // 空範囲や全検査範囲外を拒否する。
        std::cerr << "不正な範囲: " << start << ".." << end << '\n';
        return 2;
    }

    VerilatedContext context;                              // shard内で独立したVerilator状態を持つ。
    VFP32Exp dut{&context};                    // FP32 exp FTZトップを一つ生成する。
    Statistics s;                                         // shardの全指標を初期化する。
    uint32_t previous_input = 0;                           // 単調性比較の直前入力を保持する。
    uint32_t previous_actual = 0;                          // 単調性比較の直前出力を保持する。
    uint32_t first_input = 0;                              // shard境界比較用の最初の入力。
    uint32_t first_actual = 0;                             // shard境界比較用の最初の出力。
    uint32_t last_input = 0;                               // shard境界比較用の最後の入力。
    uint32_t last_actual = 0;                              // shard境界比較用の最後の出力。
    const auto begin_time = std::chrono::steady_clock::now(); // wall time計測を始める。

    for (uint64_t ordinal = start; ordinal < end; ++ordinal) { // shardの連続入力を全列挙する。
        const uint32_t input = input_from_ordinal(ordinal); // 数値昇順のbinary32入力を得る。
        dut.x = input;                                     // Verilatorモデルへ入力する。
        dut.eval();                                        // 組合せ回路を評価する。
        const uint32_t actual = dut.result;                // RTLのbinary32出力bitを読む。
        uint32_t reference;                                // correctly-rounded FTZ参照値を受ける。
        uint32_t ambiguous;                                // binary128で上下を決めにくいか受ける。
        const uint64_t bounds =                            // 同じexpqからfaithful上下限も得る。
            fp32_exp_ref_and_faithful_bounds(input, &reference, &ambiguous);
        const uint32_t lower = static_cast<uint32_t>(bounds); // faithful下限を分離する。
        const uint32_t upper = static_cast<uint32_t>(bounds >> 32); // faithful上限を分離する。
        const uint32_t ulp = ulp_distance(actual, reference); // correct参照値とのbit距離を得る。
        const bool finite_target = reference != 0 &&       // FTZ出力が0でないことを要求する。
            reference != kPositiveInfinity;               // 出力が+Infでない対象だけを選ぶ。

        ++s.total;                                         // 全検査数を進める。
        if (ambiguous != 0) ++s.faithful_ambiguous;        // 参照精度の曖昧な入力を数える。
        if (reference == 0) ++s.reference_zero;            // 参照値0を分類する。
        else if (reference == kPositiveInfinity) ++s.reference_infinity; // 参照値+Infを分類する。
        else ++s.reference_finite;                         // 非0有限normalを分類する。
        if (actual == 0) ++s.actual_zero;                  // RTL値0を分類する。
        if (actual == kPositiveInfinity) ++s.actual_infinity; // RTL値+Infを分類する。

        if (ulp == 0) ++s.correct;                         // correct一致を数える。
        else if (ulp == 1) ++s.one_ulp;                    // 1 ULP差を数える。
        else ++s.over_one_ulp;                             // 1 ULP超過を数える。
        if (ulp > s.max_ulp) {                             // 全範囲の最大ULP例を更新する。
            s.max_ulp = ulp;
            s.worst_input = input;
            s.worst_actual = actual;
            s.worst_reference = reference;
        }

        if (finite_target) {                               // ユーザ指定の非0有限出力範囲を評価する。
            if (ulp == 0) ++s.finite_correct;              // 対象範囲のcorrect一致を数える。
            else if (ulp == 1) ++s.finite_one_ulp;         // 対象範囲の1 ULP差を数える。
            else ++s.finite_over_one_ulp;                  // 対象範囲の1 ULP超過を数える。
            if (ulp > s.max_finite_ulp) {                  // 対象範囲の最大ULP例を更新する。
                s.max_finite_ulp = ulp;
                s.worst_finite_input = input;
                s.worst_finite_actual = actual;
                s.worst_finite_reference = reference;
            }
            if (actual == lower || actual == upper) {      // 厳密値を挟む二つのbinary32か調べる。
                ++s.faithful_valid;
                if (actual != reference)                  // correctでない許容隣接値を分ける。
                    ++s.faithful_alternative;
            } else {                                      // 上下限の外側ならfaithful違反とする。
                ++s.faithful_violation;
                if (actual < lower) ++s.faithful_below;    // 下側違反を数える。
                else ++s.faithful_above;                   // 上側違反を数える。
                if (s.first_faithful_ordinal == UINT64_MAX) { // 最初の違反例だけを保存する。
                    s.first_faithful_ordinal = ordinal;
                    s.first_faithful_input = input;
                    s.first_faithful_actual = actual;
                    s.first_faithful_lower = lower;
                    s.first_faithful_upper = upper;
                }
            }
        }

        if (ordinal == start) {                            // shard最初の境界値を保存する。
            first_input = input;
            first_actual = actual;
        } else if (actual < previous_actual) {             // 数値昇順入力で出力が減ったか調べる。
            ++s.monotonic_violation;
            if (s.first_monotonic_ordinal == UINT64_MAX) { // 最初の単調性違反だけを保存する。
                s.first_monotonic_ordinal = ordinal;
                s.first_monotonic_previous_input = previous_input;
                s.first_monotonic_previous_actual = previous_actual;
                s.first_monotonic_input = input;
                s.first_monotonic_actual = actual;
            }
        }
        previous_input = last_input = input;               // 次入力とshard境界用に現在値を保存する。
        previous_actual = last_actual = actual;            // 次出力とshard境界用に現在値を保存する。
    }
    dut.final();                                           // Verilatorモデルの終了処理を行う。
    const auto finish_time = std::chrono::steady_clock::now(); // wall time計測を終える。
    const double elapsed_seconds =                         // shardの経過秒へ変換する。
        std::chrono::duration<double>(finish_time - begin_time).count();
    write_json(argv[3], start, end, first_input, first_actual, // 集計に必要な全指標を保存する。
               last_input, last_actual, elapsed_seconds, s);
    return 0;                                              // shardが最後まで完了したことを返す。
}
