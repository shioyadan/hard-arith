# FP32 Exp

IEEE 754 binary32のbit patternを入力し、自然指数関数`exp(x)=e^x`を返す、
合成可能なSystemVerilog組合せ回路です。`ln(2)`による引数削減、64要素テーブル、
二次近似を使用します。

- トップモジュール: `FP32Exp`
- 出力subnormal: 既定で`+0`へflushするFTZ
- 最終仮数: 1-bit guardによる丸め
- 許容誤差: FTZ参照値に対して最大1 ULP
- インターフェース: clockなしの32-bit入出力

## ファイル構成

```text
fp32_exp/
├── fp32_exp.sv
├── README.md
├── Makefile
├── test/
│   ├── exhaustive.cpp
│   ├── reference.c
│   └── tb_fp32_exp.sv
├── tools/
│   ├── gen_constants.py
│   └── run_exhaustive.py
```

`fp32_exp.sv`だけが合成対象です。`test/`はテストベンチと参照モデル、
`tools/`は定数再生成と全数検査用です。

## インターフェース

```systemverilog
module FP32Exp #(
    parameter bit SUPPORT_SUBNORMAL = 1'b0,
    parameter bit ROUND_OUTPUT = 1'b1
) (
    input  wire [31:0] x,
    output wire [31:0] result
);
```

`x`と`result`はIEEE 754 binary32のbit patternです。clock、reset、valid、ready、
例外flag、動的な丸めモード入力はありません。標準構成ではparameterを指定せず使用します。

```systemverilog
FP32Exp u_exp (
    .x(x),
    .result(result)
);
```

`SUPPORT_SUBNORMAL=1`と`ROUND_OUTPUT=0`も記述上は選択できますが、後述の
精度検証結果は既定値の`0`と`1`に対するものです。

## 数値仕様

| 入力または条件 | 出力 |
|---|---|
| NaN | canonical quiet NaN `0x7fc00000` |
| `+Inf` | `+Inf` |
| `-Inf` | `+0` |
| `+0`、`-0`、入力subnormal | `1.0` |
| 正のoverflow | `+Inf` |
| binary32 subnormalとなる結果 | 既定構成で`+0` |

最終段は24-bit仮数と1-bit guardだけを使い、stickyとties-to-evenを持ちません。
そのためcorrect roundingは保証せず、仕様をFTZ参照値に対する最大1 ULPとしています。

## 必要なツール

- Verilator 5.x
- C++17を扱えるGCCまたはClang
- GCC libquadmath
- GNU Make
- Python 3と`mpmath`（定数の再生・照合時のみ）

Verilator 5.020、GCC 13.3.0で動作を確認しています。

## テスト

リポジトリ直下から次を実行します。

```sh
make test-fp32_exp
make lint-fp32_exp
make exhaustive-fp32_exp
make constants-check
```

`fp32_exp/`で直接`make test`、`make lint`、`make constants-check`を実行することもできます。
既定のテストは特殊値、overflow/underflow境界、引数削減境界、固定seedの20万乱数入力、
近似範囲から等間隔に選んだ20万入力の単調性を検査します。

```sh
make test-fp32_exp RANDOM_CYCLES=1000000 MONOTONIC_SAMPLES=1000000
```

参照モデルはbinary128の`expq`を使います。参照値から1 ULPを超えた場合、
または非0有限出力がfaithful上下限から外れた場合にテストは失敗します。

## 検証済み精度

近似本体へ入る指数field 102～133、両符号、全仮数fieldの
536,870,912入力をVerilatorで全列挙しました。出力subnormalはFTZ、最終丸めは
`ROUND_OUTPUT=1`、参照値はbinary128 `expq`からbinary32へ丸めてからFTZしています。

| 指標 | 全列挙範囲 | 参照出力が非0有限normal |
|---|---:|---:|
| 入力数 | 536,870,912 | 526,392,936 |
| correct参照値と一致 | 509,138,243 | 498,660,267（94.73156513%） |
| 1 ULP差 | 27,732,669 | 27,732,669 |
| 1 ULP超過 | 0 | 0 |
| 最大ULP | 1 | 1 |
| faithful違反 | ― | 0 |
| 単調性違反 | 0 | 0 |

参照出力0は5,329,840件、`+Inf`は5,148,136件で、RTLの出力数とも一致しました。
入力は数値の昇順に並べ、shard内とshard境界の単調性も検査しています。

全数検査は次のコマンドで再実行できます。

```sh
make exhaustive-fp32_exp EXHAUSTIVE_JOBS=22 EXHAUSTIVE_CHUNKS=64
```

集計結果は`fp32_exp/build/exhaustive/summary.json`と`summary.txt`へ生成されます。
これは近似データパスの全入力をbinary128参照値で検査した結果であり、
全`2^32` bit patternの列挙や形式証明ではありません。

## アルゴリズム

入力を`ln(2)/64`単位で引数削減します。

```text
n = round(x*64/ln(2))
n = 64*q+j,  0 <= j < 64
r = x-n*ln(2)/64
exp(x) ~= 2^q * 2^(j/64) * (1+r+r^2/2)
```

`n`を最近傍整数へ丸めるため、理想的には`|r|<=ln(2)/128`となります。
小さい補正を次のように分けます。

```text
T[j]*(1+r+r^2/2) = T[j]+T[j]*(r+r^2/2)
```

`1`を含む主項`T[j]`は31-bit Q30テーブルのまま加算します。
乗算するのは小さい補正だけなので、補正経路では`T[j]`の上位22-bitだけを使います。

### 処理手順

```text
neg = x[31]
exp = x[30:23]
frac = x[22:0]
if (exp == 255 && frac != 0) return QNAN
if (exp == 255) return neg ? ZERO : INF
if (exp < 102) return ONE
if (exp >= 134) return neg ? ZERO : INF

sig = {1, frac}
n_mul = sig*INV_LN2_64_Q12
n_win = n_mul[42:28]>>(133-exp)
n_abs = n_win[14:1]+n_win[0]
n = neg ? -signed16(n_abs) : signed16(n_abs)
q = n>>6
j = n[5:0]

x_abs = ({1, sig, 23'b0}>>(133-exp))
r_full = x_abs-n_abs*LN2_BY_64_Q40
r = signed23(r_full>>11)
r2_half = signed17((r*r)>>29)
r_poly = neg ? r2_half-(r<<1) : r2_half+(r<<1)

table = EXP2_TABLE_Q30[j]
table_correction = (table[30:9]*r_poly)>>21
exp_mant = table+table_correction
out_exp, sig_guard = normalize(exp_mant, q)
rounded_sig = sig_guard[24:1]+sig_guard[0]
return pack_or_flush(rounded_sig, out_exp)
```

RTLは組合せ回路なので実際には早期`return`を使いません。近似結果と特殊値結果を
並列に計算し、最後の出力選択で切り替えます。

### 固定小数点形式

`Qn`は格納整数に`2^-n`を掛けた値が実数値であることを表します。

| 信号・定数 | 幅 | 形式 | 意味 |
|---|---:|---|---|
| `INV_LN2_64_Q12` | 19 | unsigned Q12 | `round((64/ln(2))*2^12)` |
| `LN2_BY_64_Q40` | 35 | signed Q40 | `round((ln(2)/64)*2^40)` |
| `n` | 16 | signed整数 | `round(x*64/ln(2))` |
| `r_full` | 51 | signed Q40 | `|x|-n_abs*ln(2)/64` |
| `r` | 23 | signed Q29 | 二次近似へ渡す残差 |
| `r2_half` | 17 | signed Q30 | `r^2/2` |
| `r_plus_half_r2` | 25 | signed Q30 | 入力符号反映後の`r+r^2/2` |
| `EXP2_TABLE_Q30[j]` | 31 | unsigned Q30 | `round(2^(j/64)*2^30)` |
| `t_r_poly` | 27 | signed Q30 | `T[j]*(r+r^2/2)` |
| `exp_mant` | 32 | unsigned Q30 | `T[j]*(1+r+r^2/2)` |

定数とテーブルは100桁精度で次の式を最近傍偶数へ丸めて生成しています。

```text
INV_LN2_64_Q12 = round((64/ln(2))*2^12)       = 378194
LN2_BY_64_Q40  = round((ln(2)/64)*2^40)       = 11908177887
EXP2_TABLE_Q30[j] = round(2^(j/64)*2^30)      // j=0..63
```

### 主な演算資源

| ブロック | 主な幅 | 役割 |
|---|---:|---|
| 初段定数乗算 | 24×19 bit | テーブル区間`n`を選ぶ |
| 区間位置シフト | 15 bit | `q`、`j`、guardを揃える |
| Q40入力シフト | 48 bit | `|x|`を残差用Q40へ揃える |
| 残差定数乗算 | 16×35 bit | `ln(2)/64`の相殺 |
| 自乗 | 23×23 bit | `r^2/2`を作る |
| テーブル | 64×31 bit | `2^(j/64)`を復元する |
| 補正乗算 | 23×25 bit | 小さい補正を主項へ加える |
| 最終丸め | 25 bit | 仮数と指数carryを作る |

## 合成時の注意

合成トップは`FP32Exp`です。標準構成ではparameterの既定値を使用してください。
`SUPPORT_SUBNORMAL=0`が定数伝播されるため、subnormal出力用の動的シフタは除去できます。

64要素テーブルはSystemVerilogのunpacked定数配列で記述しています。合成器がこの構文を
直接扱えない場合は、同じ64値を`function`と`case`で表すROMへ変換する必要があります。
変換時はテーブル値と入出力のbit-exact一致を確認してください。

## ライセンス

Copyright 2026 Ryota Shioya

Apache License 2.0の下で公開します。詳細は[`../LICENSE`](../LICENSE)を参照してください。
