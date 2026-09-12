# FP16／BF16 Exp / Reciprocal / Rsqrt

FP16／BF16のexp、reciprocal、rsqrtを、共通の区分一次近似で計算する
組合せ演算器です。一つのRTLで、二形式の実行時切替と形式固定の両方を扱います。

- 三機能は `exp(x)`、`1/x`、`1/sqrt(x)`。
- 入出力は16 bit。形式は `is_bf16`、演算は3-bit one-hotの `op` で指定。
- 入出力subnormalに対応。有限の非zero結果は、対象形式へ最近接偶数丸めした参照値から最大1 step。
- `SUPPORT_SUBNORMAL=0` で従来の入出力FTZに切り替え可能。
- expは単調非減少、reciprocalは正負の各領域で単調非増加、rsqrtは正領域で単調非増加。
- `FORMAT_MODE` パラメータでFP16専用・BF16専用にも設定可能。

## ファイル構成

```text
fp16_bf16_exp_recip_rsqrt/
├── README.md       # 仕様、アルゴリズム、検証方法
├── Makefile        # モデル検査、RTL照合、lint、全数テスト
├── gen_rtl.py      # 係数表と共有RTLの生成
├── study.py        # 範囲縮小・中間丸めを含む整数モデル
├── reference.cpp   # 独立したbinary128参照値の生成
├── rtl_test.cpp    # 形式設定とsubnormal設定のRTL検査
├── test_study.py   # 精度・単調性・値域・丸めの検査
└── rtl/
    └── fp16.sv     # 合成対象の共有RTL
```

回路を読むときは `rtl/fp16.sv`、係数や生成規則を変更するときは `gen_rtl.py` を
入口にしてください。生成物とテスト用ビルドは `build/` 以下に置きます。

## インターフェース

```systemverilog
module FP16BF16ExpRecipRsqrtStudy #(
    parameter integer FORMAT_MODE = 0,
    parameter bit SUPPORT_SUBNORMAL = 1'b1
) (
    input wire [15:0] x,
    input wire [2:0] op,
    input wire is_bf16,
    output wire [15:0] result
);
```

| op | 演算 |
|---|---|
| `3'b001` | exp(x) |
| `3'b010` | 1/x |
| `3'b100` | 1/sqrt(x) |
| その他 | canonical quiet NaN |

| FORMAT_MODE | 対応形式 | is_bf16の扱い |
|---|---|---|
| 0（既定） | FP16とBF16 | 0: FP16、1: BF16 |
| 1 | FP16のみ | 無視する |
| 2 | BF16のみ | 無視する |

`is_bf16` は入力の解釈と出力形式を同時に選びます。形式間の変換命令ではありません。
`x`、`op`、`is_bf16` は組合せ入力であり、各評価時に変更できます。
clock、reset、valid／ready、例外flagはありません。

例えば、BF16専用として使用する場合は次のように接続します。

```systemverilog
FP16BF16ExpRecipRsqrtStudy #(.FORMAT_MODE(2)) u_arith (
    .x(x), .op(op), .is_bf16(1'b0), .result(result)
);
```

専用設定でもポート構成は同じです。0、1、2以外の `FORMAT_MODE` はサポートしません。
`SUPPORT_SUBNORMAL` は合成時の設定です。既定の1では両形式の入出力subnormalを扱い、
0では従来通り入出力FTZとします。実行時の切替入力は追加しません。

## 数値仕様

| 項目 | FP16 | BF16 |
|---|---|---|
| 符号／指数／fraction | 1／5／10 bit | 1／8／7 bit |
| 指数bias | 15 | 127 |
| +Inf | `16'h7c00` | `16'h7f80` |
| canonical quiet NaN | `16'h7e00` | `16'h7fc0` |

既定では入力subnormalを非zeroの値として扱い、出力subnormalも保持します。
出力丸めは最近接偶数丸め（RNE: round to nearest, ties to even）を使用します。
`SUPPORT_SUBNORMAL=0` では入力subnormalを符号付きzeroとして扱い、
出力を対象形式へRNEした後でsubnormalを符号付きzeroへflushします。
NaNの符号とpayloadは保持しません。

| 入力 | exp | reciprocal | rsqrt |
|---|---|---|---|
| NaN | canonical qNaN | canonical qNaN | canonical qNaN |
| ±0 | 1 | ±Inf | ±Inf |
| 正のsubnormal | 1 | 正の逆数近似値（overflow時は+Inf） | 正の逆数平方根近似値 |
| 負のsubnormal | 1 | 負の逆数近似値（overflow時は−Inf） | canonical qNaN |
| +Inf | +Inf | +0 | +0 |
| −Inf | +0 | −0 | canonical qNaN |
| 負のnormal | 正のexp近似値 | 負の逆数近似値 | canonical qNaN |

有限の非zero結果（normalとsubnormal）の誤差は、独立した高精度計算を対象形式へRNEした参照値との
**表現可能な値の間隔で最大1 step**です。正しく丸めた結果そのものや、
真値を挟む隣接二値のいずれかを返すfaithful roundingは要求しません。
参照値または出力がzero・Inf・NaNの場合や符号が異なる場合は、参照値とbit一致させます。
このため、最大1 stepという条件によって、zeroやInfへの誤った遷移を許容しません。
FTZ設定の参照値には同じ入出力FTZを適用し、従来のnormal結果最大1 stepを維持します。

単調性は、丸めによって同じ出力が続くことを許す条件です。
expは入力が増えても出力が減らない「単調非減少」、
reciprocalとrsqrtは入力が増えても出力が増えない「単調非増加」とします。
reciprocalは零点をまたがず、負領域と正領域を別々に検査します。
rsqrtは `+0～+Inf` を対象とし、負入力の特殊値処理とは区別します。

## 必要なツール

- GNU Make
- C++17 compilerとbinary128演算に対応したlibm
- Python 3、NumPy、mpmath
- Verilator

合成対象はSystemVerilogだけです。Pythonとbinary128演算は定数生成・検証に使用し、
RTLの計算には含みません。

## テスト

以下は、このREADMEがある `fp16_bf16_exp_recip_rsqrt/` で実行します。

```sh
# 整数モデルの精度・単調性・丸めなどを検査
make model-test

# 整数モデルと既定設定のRTLを検査
make test

# 生成RTLとの一致とlint
make rtl-check
make rtl-lint

# 実行時形式切替・subnormal対応のRTLを全数検査
make rtl-test

# FP16専用、BF16専用をそれぞれ全数検査
make rtl-test FORMAT_MODE=1
make rtl-test FORMAT_MODE=2

# 従来のFTZ設定を全数検査
make rtl-test SUPPORT_SUBNORMAL=0

# モデル検査と形式3設定×subnormal 2設定のRTL全数検査
make rtl-test-all
```

他の演算器と同じ `lint`、`constants-check`、`exhaustive`、`monotonic` も使用できます。
`exhaustive` はモデル検査と6設定のRTL全数検査、`monotonic` はモデルの全入力検査を実行します。
リポジトリ直下では、例えば `make exhaustive-fp16_bf16_exp_recip_rsqrt` と指定します。
互換性のため、module名 `FP16BF16ExpRecipRsqrtStudy` と従来の `rtl-*` targetは維持します。

`reference.cpp` は近似モデルから独立したbinary128演算で参照値を求め、
FP32やdoubleを中継せず対象形式へ直接RNEします。
`test_study.py` は、この参照値に対する全入力精度・単調性を検査し、
境界値と固定seedの標本では独立した100桁演算とも照合します。

`rtl-test` は全16-bit入力、有効3 opと無効5 op、形式入力の0と1を組み合わせた
1,048,576組を検査します。有効opでは整数モデルとbit一致、無効opではcanonical qNaNを
確認します。各 `x`・`op` で形式入力を交互に切り替えるため、専用設定では
`is_bf16` に出力が依存しないことも検査します。

## 検証済み精度

以下はsubnormal対応・FTZの両設定で確認した結果です。

| 形式 | 演算 | 入力数 | 最大RNE step | 精度違反 | 単調性違反 |
|---|---|---:|---:|---:|---:|
| FP16 | exp | 65,536 | 1 | 0 | 0 |
| FP16 | reciprocal | 65,536 | 1 | 0 | 0 |
| FP16 | rsqrt | 65,536 | 1 | 0 | 0 |
| BF16 | exp | 65,536 | 1 | 0 | 0 |
| BF16 | reciprocal | 65,536 | 1 | 0 | 0 |
| BF16 | rsqrt | 65,536 | 1 | 0 | 0 |

特殊値、subnormal、FTZ、overflow境界も全入力精度検査に含みます。
RTLは三つの `FORMAT_MODE` と二つの `SUPPORT_SUBNORMAL` で合計6,291,456組のbit一致を確認しています。
残差・傾きの量子化と中間丸めを小型化したため、以前の9×11近似乗算の版とは一部の出力が変わります。
対応ON／FTZのどちらも上記の精度・単調性仕様を維持します。
また、正規化を固定できる値域と丸め条件を検査し、全指数とunderflow／overflow境界を
含めて汎用packとの一致を確認しています。これらは全数simulationであり、形式証明ではありません。

## アルゴリズム

### 基本的な考え方

まず、2の累乗による倍率と、実際に近似しなければならない部分を分けます。
reciprocalでは入力指数の符号を反転すれば倍率が求まり、残る仕事は仮数の逆数だけです。
rsqrtでも指数を半分にでき、expでは入力を2の指数へ変換することで同じ形にそろえます。

三関数の処理は、次の三段階です。

1. 関数別に範囲を縮小し、近似する値を狭い区間へ移す。
2. 小さな区間ごとの係数を選び、共通の `P(d) = c0 + c1*d` で近似する。
3. 指数で倍率を戻し、対象形式へ丸めて特殊値を選択する。

2の累乗を掛ける処理は出力指数で表現できるため、乗算器は不要です。
近似カーネルの乗算・加算・出力処理を三関数で共有し、
expに必要な初段の定数乗算だけを別に持ちます。
ここではニュートン反復を行わず、区分一次近似だけで16-bit形式の誤差条件を満たします。

#### 1. 指数と近似部分の分離

normal入力を `x = (-1)^s * 2^E * m`、`1 <= m < 2` と表すと、
reciprocalは次のように分かれます。

```text
1/x = (-1)^s * 2^(-E) * (1/m)
```

符号を保持し、指数を反転して、`1/m` だけを近似します。
subnormal入力は仮数を左へshiftして同じ `1 <= m < 2` の形へ正規化し、その分だけ指数を補正します。
既存の仮数格子へ無誤差で移せるため、subnormal専用の係数表は不要です。

rsqrtは正入力に対し、指数を `E = 2*k + p`、
`k = floor(E/2)`、`p = 0 または 1` と分けます。

```text
1/sqrt(x) = 2^(-k) * 1/sqrt(2^p * m)
```

指数の偶奇を係数表の選択に含めれば、近似部分はどちらの偶奇でも `(0.5,1]` に収まります。
reciprocalの `m=1` と、rsqrtの `m=1 かつ p=0` は、厳密値1を返す別経路にします。

expは入力を2の指数へ変換し、整数部と小数部に分けます。

```text
z = x * log2(e) = k + t    （k = floor(z)、0 <= t < 1）
exp(x) = 2^k * 2^t
```

以後は `2^t` だけを近似します。この表式は実数上の関係であり、
実装では `log2(e)` と `z` の量子化誤差も含めて精度を検査します。

#### 2. 狭い区間を直線で近似

expでは上記の `t`、reciprocalとrsqrtでは `t=m-1` を区間選択に使います。
いずれも `[0,1)` を等分し、区間中心からの差 `d` を求めます。

```text
j = floor(2^b * t)
Cj = (j + 1/2) / 2^b
d = t - Cj
P(d) = c0[j] + c1[j] * d
```

区間を狭くすれば、関数の曲がりによる直線近似の誤差は区間幅の二乗に応じて小さくなります。
係数は区間内の二つの補間点から求めます。半幅を `h=2^(-b-1)` とすると、
補間点は中心から `±h/sqrt(2)` の位置です。区間の両端を結ぶ直線ではなく、
内部の点で合わせて区間全体の誤差を抑えます。

ここで `c0` は補間直線の中心での値、`c1` は傾きです。
三関数で係数だけを切り替えれば、同じ乗算と加算を使用できます。
係数量子化と中間丸めも誤差に加わるため、区間数だけで合否を決めず、最後まで計算して検査します。

| 形式 | expの区間数 | reciprocalの区間数 | rsqrtの区間数 | 係数の小数bit数 c0／c1 |
|---|---:|---:|---:|---|
| FP16 | 16 | 16 | 16 × 偶奇2通り | 13／7 |
| BF16 | 4 | 8 | 4 × 偶奇2通り | 9／5 |

各区間は `c0,c1` の組を持ちます。rsqrtの表要素数は偶奇を合わせてFP16が32、BF16が8です。
形式と関数ごとに表を分けますが、表から読み出した後の計算は共有します。

### 実装

#### 1. expの範囲縮小

入力仮数をQ10へそろえ、Q14の定数 `23637 = RNE(log2(e) * 2^14)` を掛けます。
Qnは、格納する整数を `2^n` で割って読む固定小数点形式です。
BF16仮数の下位に3-bitのzeroを補うことで、FP16と同じunsigned 11×15の定数乗算式を使います。

先に、近似が不要な入力範囲を除きます。FP16の有限入力では `|x| >= 32`、BF16では
`|x| >= 128` なら、正入力の結果は+Inf、負入力の結果はRNEで+0に確定します。
subnormal対応のON/OFFによらず成立し、非zeroのsubnormal結果を捨てる変更ではありません。
NaN・無効opなどの特殊値判定は、この分岐より優先します。

積はQ24です。指数に応じてshiftし、FP16ではQ13、BF16ではQ9の `z` へRNEします。
右shift量はFP16で `26-指数field`、BF16で `142-指数field` です。
RTLでは減算器でshift量を求めず、指数fieldと定数を直接比較して配線の枝を選びます。
近似する範囲だけなら、丸め後の絶対値は19 bitに収まります。
保持19 bit・guard・stickyの計21 bitを選び、一度だけ丸めた後、符号付き20 bitの `z` にします。
小数精度はQ13／Q9のままで、削るのは不要になった整数側の上位bitです。

stickyは積の完成を待たず、入力仮数から求めます。定数23637は奇数なので、
積の下位k bitがすべてzeroとなる条件は、入力仮数の下位k bitがすべてzeroとなる条件と一致します。
Q10仮数のbit10は暗黙の1であり、11 bit以上をORするstickyは常に1です。
保持部とguardは積から選び、stickyだけをこの恒等式で置き換えるため、tieを含むRNE結果は変わりません。

符号を反映した `z` の整数部が出力倍率、小数部がテーブル入力です。
`test_shared_runtime_datapath`でstickyの恒等式、19-bitの値域、独立参照値による上記の境界を確認します。
整数モデルは広い範囲と整数幅を維持し、全6設定のRTL照合で幅削減前と同じ出力になることも検査します。

#### 2. 係数選択と共有一次近似

範囲縮小後の固定小数点値の上位bitで区間を選び、下位bitで中心との差を表します。
区間中央を引く処理は、下位部分の最上位bitを反転してsigned値として読むだけです。
大きな減算器は必要ありません。

`c0` はFP16でQ13、BF16でQ9です。範囲縮小値も同じ精度を保ちますが、
乗算に渡す残差 `d` はそれぞれ下位2 bit／1 bitを負方向へ切り下げ、Q11／Q8にします。
reciprocal／rsqrtでは削るbitがもともとzeroなので、この残差削減自体は無誤差です。
expでは残差の量子化誤差が加わるため、最終出力の精度・単調性を全入力で検査します。

`c1` はFP16でQ7、BF16でQ5です。積を5 bitまたは4 bit負方向へ切り下げて
`c0` と同じ小数点位置へ戻し、加算します。中間にはRNE加算を置かず、最終出力だけRNEします。

| 信号・演算 | 共有RTLの幅 | FP16の小数bit数 | BF16の小数bit数 |
|---|---|---:|---:|
| 残差 d | signed 7 bit | 11 | 8 |
| 係数 c1 | signed 9 bit | 7 | 5 |
| d*c1 | signed 16 bit | 18 | 13 |
| 係数 c0 | unsigned 14 bit | 13 | 9 |
| 切り下げ後の補正・加算結果 | signed 16 bit | 13 | 9 |
| 近似結果 y | unsigned 14 bit | 13 | 9 |

BF16だけなら近似乗算に必要な幅はsigned 6×7ですが、
共有RTLではsigned 7×9へ符号拡張して入力します。
三関数で係数の小数点位置をそろえることで、積の切り下げ位置は形式だけで選択できます。

#### 3. 正規化とpack

最終段では、近似結果の完成を待って先頭bitを調べる代わりに、
演算種別と厳密点判定から正規化位置を先に決めます。

- reciprocal／rsqrtの厳密点以外は `[0.5,1)` に収まり、対象形式へのRNEでも1に達しません。
  仮数を2倍し、指数を1減らす位置に固定します。厳密値1の点では指数を変えません。
- expは指数を変えない位置に固定します。近似値は2未満で、最小値はFP16が
  `8190/8192`、BF16が `511/512` と1を少し下回りますが、どちらも最終RNEで1になります。
  この位置でも汎用の値依存正規化と同じ出力になります。

近似結果は14 bitに収まります。まず三通りの固定位置から保持部・guard・stickyを選びます。
subnormal出力では、さらに指数不足分だけ右shiftし、捨てたbitをstickyへ集約します。
最終RNEを一度だけ行うため、normalへ丸めてからsubnormalへ丸め直す二重丸めは起こしません。
現行の係数・残差幅・中間floorでは、normal位置で最終RNEした仮数は
FP16で最大2047、BF16で最大255です。隠れbitを含めても2に達しないため、
指数carryとcarry時の仮数shiftを省き、最終仮数は11 bitで保持します。
subnormal時の右shiftはこの上限を増やしません。最小normalへの丸め上がりは
隠れbitの判定で残し、仮数が2になるcarryとは区別します。
FTZ設定では追加の右shift回路を定数化で除き、最小normalへ丸め上がらない結果をzeroにします。
最後に符号と特殊値を選びます。

正規化固定は、現在の係数と丸め位置による値域を前提とする最適化です。
`test_fixed_normalization_exhaustive` と `test_subnormal_exhaustive` で前提と全入力のpack一致を確認し、
整数モデルの汎用packは独立した比較対象として維持します。

#### 4. subnormal対応で追加する回路

reciprocal／rsqrtの入力には、仮数の先頭zero検出、左shift、指数補正を追加します。
BF16の7-bit fractionもFP16と同じ10-bit位置へ上詰めし、同じ回路を使います。
正規化後のfractionと指数偶奇から、従来と同じ係数表と厳密点を選びます。
expのsubnormal入力は、両形式とも正しく丸めると1になるため、近似経路へは渡しません。

出力には、保持部・guard・stickyを合わせた13 bitの右shift回路を追加します。
1／2／4／8 bitの四段でshiftし、各段で捨てるbitの論理和をstickyへ引き継ぎます。
13 bit以上は必ずzeroへ丸まるため、shift量は4 bitで十分です。
rsqrtは正の有限入力からsubnormal結果を生じず、この経路を必要とするのはexpとreciprocalです。

#### 主な演算資源

乗算式は、expの範囲縮小用のunsigned 11×15定数乗算と、
三関数で共有するsigned 7×9近似乗算の二つです。
係数表は形式・関数別ですが、近似の加算と出力の丸め・指数復元は共有します。

専用設定では、内部の形式選択を一か所で定数化します。
不要な表・選択回路・上位bitの除去は合成器へ任せ、専用RTLや別カーネルは追加しません。
subnormal対応も同じRTL内の合成時設定であり、係数・乗算器は両設定で共通です。

## 定数とテーブルの照合

係数とRTLの生成規則は `gen_rtl.py` と `study.py` を正本とし、
数値列や生成RTLだけを手編集しません。

```sh
# 現在のRTLが生成結果と一致することを確認
make rtl-check

# 生成規則を変更した場合にRTLを更新し、全体を検証
make rtl-generate
make rtl-test-all
```

`rtl-check` は係数表だけでなくRTL全体の再生成一致を確認します。
係数や幅を変えた場合は、精度・単調性に加えて正規化固定の前提も再検査します。

## 合成時の注意

合成対象は `rtl/fp16.sv`、トップは `FP16BF16ExpRecipRsqrtStudy` です。
SystemVerilogのunpacked定数配列に対応したフローを使用してください。
clockを持たないため、入力から出力までの組合せパスに遅延制約を与えます。

`FORMAT_MODE=0` では `is_bf16` もデータパスの入力です。
二形式切替と専用設定の評価では、`FORMAT_MODE` と `SUPPORT_SUBNORMAL` の両方を記録してください。
定数乗算の分解や不要bitの削除を含む実際の演算資源は、合成結果で確認します。

## ライセンス

Copyright 2026 Ryota Shioya and Toru Koizumi

Apache License 2.0で公開します。詳細は [LICENSE](../LICENSE) を参照してください。
