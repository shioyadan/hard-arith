# FP32 Exp / Reciprocal / Inverse Square Root

IEEE 754 binary32のbit patternと演算選択を入力し、自然指数関数`exp(x)=e^x`、
逆数`1/x`、逆平方根`1/sqrt(x)`のいずれかを返す、合成可能なSystemVerilog
組合せ回路です。同時には一演算しか実行しないことを利用し、三関数の二次近似を
一つのHorner datapathへ載せ、二段の乗算器と結果生成回路を共有します。

- トップモジュール: `FP32ExpRecipRsqrt`
- インターフェース: clockなしの32-bit入出力と3-bit one-hot `op`
- subnormal: 合成時に入出力対応を選択（既定はFTZ）
- 精度: 有限非zero結果はRNE参照値から最大1 step
- 単調性: 各演算の非NaNな定義域内で保持
- 共有datapath: signed 18 x unsigned 9 bitとsigned 18 x signed 20 bitの乗算を各1個

## ファイル構成

```text
fp32_exp_recip_rsqrt/
├── fp32_exp_recip_rsqrt.sv
├── README.md
├── Makefile
├── test/
│   ├── exhaustive_exp.cpp
│   ├── exhaustive_recip.cpp
│   ├── exhaustive_rsqrt.cpp
│   ├── configs.sv
│   ├── configs.cpp
│   ├── monotonic_exp.cpp
│   ├── monotonic_recip.cpp
│   ├── monotonic_rsqrt.cpp
│   ├── reference.c
│   └── tb_fp32_exp_recip_rsqrt.sv
└── tools/
    └── gen_constants.py
```

`fp32_exp_recip_rsqrt.sv`だけが合成対象です。`test/`はquick test、縮約全数検査、
全入力検査、単調性検査、`tools/`は係数tableの再生成・転記ミス検査に使います。

## インターフェース

```systemverilog
module FP32ExpRecipRsqrt #(
    parameter bit SUPPORT_SUBNORMAL = 1'b0
) (
    input  wire [31:0] x,
    input  wire [2:0]  op,
    output wire [31:0] result
);
```

`x`と`result`はIEEE 754 binary32のbit patternです。clock、reset、valid、ready、
例外flag、NaN payload保持、動的な丸めモード入力はありません。

`op`はone-hotで、次のbit割当を公開インターフェースとします。

| `op` | 演算 |
|---:|---|
| `3'b001` | `exp(x)` |
| `3'b010` | `1/x` |
| `3'b100` | `1/sqrt(x)` |

未定義の`op`または複数bitが立った`op`にはcanonical quiet NaN
`0x7fc00000`を返します。

```systemverilog
FP32ExpRecipRsqrt u_elem3 (
    .x(x),
    .op(op),
    .result(result)
);
```

## 合成時パラメータ

| パラメータ | 既定値 | 設定値 | 制御する内容 |
|---|---:|---|---|
| `SUPPORT_SUBNORMAL` | `0` | `0` / `1` | `0`: 入出力FTZ、`1`: 入力subnormalの正規化と出力gradual underflow |

`FP32ExpRecipRsqrt #(.SUPPORT_SUBNORMAL(1'b1))`でsubnormal対応を有効にします。
設定は合成時に固定し、実行時に切り替える信号ではありません。OFF側は従来のFTZ出力を維持します。
exp／recip／rsqrtは常に三機能を備え、`op`で実行時に選びます。
機能ごとの`ENABLE_*`、入出力幅・近似精度を変更する設定はありません。

## 数値仕様

有限非zero結果は、無限精度値をround-to-nearest-evenでbinary32へ丸めた参照値から
最大1 representable stepとします。subnormal域では1 stepは`2^-149`です。
OFF側は入出力をFTZとして比較し、normal結果で最大1 ULPです。
この条件は、厳密値を挟む二つのbinary32値のどちらかを返す
strict faithful roundingとは同一ではありません。

| 入力または条件 | `exp(x)` | `1/x` | `1/sqrt(x)` |
|---|---|---|---|
| NaN | canonical qNaN | canonical qNaN | canonical qNaN |
| `+Inf` | `+Inf` | `+0` | `+0` |
| `-Inf` | `+0` | `-0` | canonical qNaN |
| `+0` / `-0` | `1.0` | `+Inf` / `-Inf` | `+Inf` / `-Inf` |
| 入力subnormal（OFF） | `1.0` | signed zeroとして扱う | signed zeroとして扱う |
| 入力subnormal（ON） | `1.0` | 非zero値として計算。overflowはsigned Inf | 正は計算、負はcanonical qNaN |
| 出力subnormal（OFF） | `+0`へflush | signed zeroへflush | 発生しない |
| 出力subnormal（ON） | 保持 | 保持 | 発生しない |

NaN、Inf、signed zeroの分類は誤差許容とは別に保持します。
ON側のrecipは入力の絶対値が`0x00200000`以下の非zero subnormalでoverflowし、
`0x00200001`以上では有限値です。負のsubnormalのrsqrtは、`rsqrt(-0)=-Inf`とは区別します。

`exp`は非NaN入力に対して単調非減少です。`1/x`は零点に極があるため、負領域
`-Inf`から`-0`と正領域`+0`から`+Inf`を別々に扱い、それぞれで単調非増加です。
`1/sqrt(x)`は`+0`から`+Inf`まで単調非増加です。負の非zero入力と`-Inf`はNaNを
返すため、逆平方根の単調性の定義域に含めません。ただしOFF側の負subnormal入力はsigned zero扱いです。

## 必要なツール

- Verilator 5.x
- C++20、OpenMP、libquadmathを扱えるGCCまたはClang
- GNU Make
- Python 3とNumPy

Dev containerにはこれらを導入済みです。Verilator 5.020、GCC 13.3.0で
動作を確認しています。

## テスト

リポジトリ直下から次を実行します。

```sh
make lint-fp32_exp_recip_rsqrt
make test-fp32_exp_recip_rsqrt
make exhaustive-active-fp32_exp_recip_rsqrt EXHAUSTIVE_THREADS=22
make exhaustive-fp32_exp_recip_rsqrt EXHAUSTIVE_THREADS=22
make monotonic-fp32_exp_recip_rsqrt MONOTONIC_THREADS=22
make constants-check-fp32_exp_recip_rsqrt
make test-configs-fp32_exp_recip_rsqrt
make test-fp32_exp_recip_rsqrt SUPPORT_SUBNORMAL=1
make exhaustive-fp32_exp_recip_rsqrt SUPPORT_SUBNORMAL=1 EXHAUSTIVE_THREADS=12
make monotonic-fp32_exp_recip_rsqrt SUPPORT_SUBNORMAL=1 MONOTONIC_THREADS=8
```

`fp32_exp_recip_rsqrt/`内では、それぞれ`make lint`、`make test`、
`make exhaustive-active`、`make exhaustive`、`make monotonic`、
`make constants-check`です。
`SUPPORT_SUBNORMAL=0/1`を指定でき、生成物は`build/subnormal-0/1/`へ分離します。
`make test-configs`は両設定を同時に検査するため、この設定に依存しません。

`make test`は特殊値、overflow／underflow境界、引数還元境界、table index境界、
固定seedの各200,000乱数入力をbinary128参照値で検査します。また、各演算から
等間隔に選んだ200,000入力について隣り合う出力を比較します。

`make exhaustive-active`は、`exp`の近似本体へ入る536,870,912入力、逆数の
全8,388,607非零仮数、逆平方根の指数偶奇2通りの全16,777,216仮数を検査します。
`make exhaustive`へ置き換えると、`exp`は全`2^32`入力を検査します。

`exp`はbinary128 `expq`をRNE参照値に使います。根系はRTLのtableや演算に依存しない
厳密整数参照モデルからRNE値を生成します。逆数と逆平方根では近似本体が指数値そのものに
依存しないことを利用し、全仮数に加えて全指数境界と特殊値を検査します。

`make monotonic`は、`exp`ではNaNを除く全4,278,190,081隣接組、根系では
縮約可能な全隣接仮数と指数境界を検査します。

`make test-configs`は両設定の根系全仮数、正負subnormal全入力、recipの出力subnormal域、
expの`-87 .. -129`全入力、全指数境界、特殊値、無効opを検査します。
根系の参照値は整数の商・余り、または128-bit整数の平方比較で作り、
境界標本ではbinary128参照関数とも照合します。根系のsubnormal域の単調性もここで検査します。
ON側の`exhaustive`／`exhaustive-active`は、この両設定検査とexp走査を実行します。
通常経路では両設定のbit一致も確認します。

## 検証済み精度

固定seed各200,036入力と各200,000単調性標本では次を確認しています。数値の順はOFF／ONです。

| 指標 | `exp(x)` | `1/x` | `1/sqrt(x)` |
|---|---:|---:|---:|
| RNE一致 | 172,439 / 172,267 | 159,903 / 159,529 | 158,234 / 158,232 |
| RNEからの最大step数 | 1 | 1 | 1 |
| 単調性標本違反 | 0 | 0 | 0 |

OFF基準版の`exp`は全4,294,967,296入力をbinary128 `expq`参照値で検査し、normal結果
2,262,834,792入力で最大1 step、FTZ対象1,020,351,408入力とoverflow対象
995,003,880入力で不一致0でした。非NaN全4,278,190,081隣接組でも単調性違反0です。

逆数は全8,388,607非零仮数、逆平方根は指数偶奇別の全16,777,216仮数を検査し、
RNE参照値から最大1 stepでした。逆数の全16,777,214隣接仮数と512指数境界、
逆平方根の全16,777,214隣接仮数と256指数境界でも単調性違反0です。

ON側もexp全4,294,967,296入力で最大1 RNE step、特殊値・zero・overflow分類不一致0、
非NaN全4,278,190,081隣接組で単調性違反0を確認しました。
追加した根系の正負subnormal全入力、recipの入力指数field 253／254の全仮数でも、
最大1 step・分類不一致0・単調性違反0です。OFF側は旧RTLとexp全入力、
根系の全仮数・全subnormal・指数境界等の検査集合でbit一致しました。
expの実数誤差の最大値はnormal約1.4635 ULP、subnormal約1.0978 ULPであり、
RNEから最大1 stepという条件と、実数誤差1 ULP未満やfaithfulとは区別します。

これらはVerilated RTLモデルによる離散入力の列挙検査であり、形式証明や
精度保証付きの計算機援用証明ではありません。

## アルゴリズム

### 基本的な考え方

三つの関数は広い入力範囲をそのまま多項式で近似しません。最初に2の累乗で表せる
部分を分離し、出力の指数fieldで処理します。回路で近似するのは、狭い範囲へ還元した
残差または仮数関数だけです。

```text
exp(x)       = 2^q * 2^(j/64) * exp(r)
1/x          = (-1)^s * 2^(-E) * 1/m
1/sqrt(x)    = 2^(-q) * 1/sqrt(m*2^p),  E=2q+p
```

- `exp`は`x`を64分割した`ln(2)`格子へ還元し、小さい残差`r`だけを近似する
- 逆数は符号と指数を分離し、`1 <= m < 2`にある仮数の`1/m`だけを近似する
- 逆平方根は指数を半分にし、指数の偶奇`p`を仮数近似側へ吸収する

この分解により、大きな値域を乗算器で扱う必要がなくなります。三関数の還元方法は
異なりますが、還元後の関数はすべて同じ二次Horner回路で評価します。

### `exp(x)`の引数還元

自然指数関数を底2へ変換し、`x*64/ln(2)`に最も近い整数`n`を求めます。

```text
n = round(x*64/ln(2))
n = 64*q+j,  0 <= j < 64
r = x-n*ln(2)/64
exp(x) = 2^q * 2^(j/64) * exp(r)
```

`2^q`は出力指数で表します。残差は`|r|`がおよそ`ln(2)/128`以下なので、
`2^(j/64)*exp(r)`を64行の二次係数で近似します。

### `1/x`の指数分離

normal入力を符号`s`、仮数`m`、非バイアス指数`E`へ分けます。

```text
x   = (-1)^s * m * 2^E,  1 <= m < 2
1/x = (-1)^s * (1/m) * 2^(-E)
```

符号は入力から引き継ぎ、2の累乗は出力指数の減算で処理します。近似回路が
計算するのは`[1,2)`上の`1/m`だけです。仮数を128区間へ分け、区間内位置を
中心基準の残差`d`として二次近似します。

### `1/sqrt(x)`の指数分離

正のnormal入力の指数を偶数部分と偶奇へ分けます。

```text
x = m*2^E
E = 2q+p,  p in {0,1}
1/sqrt(x) = 2^(-q) * 1/sqrt(m*2^p)
```

`p=0`では`1/sqrt(m)`、`p=1`では`1/sqrt(2*m)`を近似します。このため、128行の
係数をbase用とscaled用の2組持ちます。指数値そのものは近似結果に影響せず、
偶奇だけが係数bankの選択に使われます。

### subnormal入力の正規化

ON側では根系の入力fraction整数`F`を先頭の1まで左shiftします。
`s=clz23(F)+1`、仮数整数`M=F<<s`、指数`E=-126-s`とすれば、normal入力と同じ
`1<=m<2`の格子へ戻せます。recip／rsqrtで16／8／4／2／1 bitの段階shiftを共有し、
正規化後のfractionを既存tableへ渡します。rsqrtの指数偶奇は`s`の最下位bitです。
表とHorner乗算器の幅は変えません。expのsubnormal入力は常に1へ丸まるため正規化不要です。

recipの小さいsubnormal入力は先にoverflowへ分岐します。残る有限入力のshiftは1／2のみで、
出力指数は`252+s+exact`です。rsqrtは`189+(s>>1)+(s&1)+exact`となります。
どちらも8-bit指数経路で足り、通常経路の指数幅を一律には広げません。

### 共通Hornerデータパス

還元後の三関数を同じ二次式へ揃えます。

```text
P(d) = C0+d*(C1+d*C2)

inner = C1+round(d*C2)
P(d)  = C0+round(d*inner)
```

RTLでは数式上の`P(d)`をQ27の全幅で作らず、最後のC0加算と出力丸めを統合し、
必要なQ24仮数を直接生成します。二つの乗算と、その直後の中間丸めは変更しません。

```text
x, op
  |
  +-- 特殊値分類
  |
  +-- exp: ln(2)/64引数還元 ---- exp 64行係数 ---+
  |                                               |
  +-- root: 仮数128区間化 ------- 関数別係数 -----+
                                                  |
                         共有乗算 第1段
                              d*C2
                                                  |
                         共有乗算 第2段
                            d*inner
                                                  |
                     共通C0加算＋最終丸め
                                                  |
                        指数・特殊値処理
                                                  |
                                                result
```

`exp`ではC0だけを64行のQ27 tableに格納します。元のQ17のC1は
`(C0 >> 10)+(1または2)`、Q9のC2は`(C0 >> 19)+(0または1)`で正確に表せるため、
補正値を示す64-bit maskを各1本だけ保持し、C1/C2のtableは置きません。C1は
演算時にQ18へ揃えます。Q27からQ24への出力切り詰めに必要な丸めbiasはC0へ
織り込み、Q24生成には独立した丸め加算器を置きません。table境界で精度または単調性が
厳しい6区間だけC0を調整しています。

根系には`FP32Elementary`と同じQ25/Q17/Q8係数を使います。読み出し時に下位zeroを
追加し、C0=Q27、C1=Q18、C2=Q9、差分=Q24の共通形式へ揃えます。到達範囲を
全table行で検査した上で、差分はsigned 18 bit、C1はsigned 20 bit、C2は
unsigned 9 bitに絞っています。共有乗算器はsigned 18 x unsigned 9 bitと
signed 18 x signed 20 bitを各1個です。

#### 固定小数点形式

`Qn`は格納整数に`2^-n`を掛けた値を表す固定小数点形式です。

| 信号・係数 | 格納形式 | 演算時の形式 | 役割 |
|---|---:|---:|---|
| exp `C0/C1/C2` | C0: Q27、C1/C2: C0とmaskから再構成 | Q27 / Q18 / Q9 | `2^(j/64)*exp(r)`の近似 |
| reciprocal `C0/C1/C2` | Q25 / Q17 / Q8 | Q27 / Q18 / Q9 | `1/m`の近似 |
| rsqrt `C0/C1/C2` | Q25 / Q17 / Q8 | Q27 / Q18 / Q9 | 偶奇別の逆平方根近似 |
| exp残差 | signed Q24 | signed Q24 | `ln(2)/64`格子からの位置 |
| root残差 | signed Q23 | signed Q24 | 128分割区間中心からの位置 |
| 外側補正 | Q27 | Q27 | `d*inner`を中間丸めした値 |
| 最終仮数 | Q24 | Q24 | C0加算と出力丸めを統合した結果 |

根系の各係数bankでは、全行に共通する上位bitをprefixとして一度だけ保持し、
行ごとのsuffixだけをtableへ格納します。省いた下位bitは読み出し時にzeroとして
復元します。expではさらにC1/C2の相関を利用し、二つの係数tableをC0直結bitと
128 bitの補正maskへ置き換えています。

### 結果の丸めと指数

根系では、厳密な二のべき点を除く近似値が`[0.5,1.0)`に収まり、RNE後も`1.0`へ
桁上がりしません。この条件を係数生成時に全仮数で検査することで、正規化位置の選択と、
丸めcarryを待つ指数補正を省いています。厳密点だけは最終fractionを0とし、指数を1段補正します。

残る仮数生成は、C0との加算と最終丸めを一つの25-bit加算へまとめます。
丸め済みの外側補正を`K`として、上位と下位3 bitを分けると次の形になります。

```text
A = C0 >> 3
B = K >>> 3                    // 負の補正も符号付きで扱う
s = (C0 & 7) + (K & 7)

exp_carry  = (s >= 8)
root_carry = (s > 4) || ((s == 4) && ((A ^ B) & 1))
mantissa_q24 = A + B + carry
```

expはC0へ最終biasを織り込んであるので、ここでは切り捨てのcarryだけを反映します。
根系のC0はQ25からQ27へ揃える際に下位2 bitを0としているため、`s`は最大11です。
低位加算でcarryが出た場合の残りは最大3なので、RNEの追加carryは出ません。
したがって二つのcarryが同時に起こることはなく、上位和へ加える補正は0か1だけです。
`s==4`では上位和の偶奇を使い、tie-to-evenを維持します。

指数は仮数経路を待たず、入力指数field`B_in`から直接計算します。
`p=~B_in[0]`、厳密点を`e`（0または1）とすると、normal入力の出力指数fieldは
逆数で`253-B_in+e`、逆平方根で`189-(B_in>>1)+p+e`です。
逆数の出力FTZ条件は`B_in==254 || (B_in==253 && !e)`へ簡約できます。
normal入力では根系のoverflowはなく、逆平方根のunderflowもありません。
zero入力のInf、OFF側subnormalのFTZ、NaN／負入力の処理は別の特殊値経路で行います。

ON側の出力subnormalは通常結果のpackとは分け、共通Q24仮数から作ります。
recipは入力指数fieldが253／254のとき追加1／2 bitの右shiftとRNEを行い、
厳密点ではQ24の1.0を使います。既存RNE後の値を再利用する二重丸めですが、
最終的な最大1 stepと単調性は全仮数で検査しています。Q27から直接丸める回路ではありません。

expはQ24仮数を`-q-125` bit右shiftし、guardとstickyを保持してRNEします。
`q<-150`はzeroへ飽和させ、5-bit shift量のwrapを防ぎます。
最小normalへの丸め上がりはpayloadのbit 23で表せます。
rsqrtでは、全ての正の有限入力に対して結果がnormalの範囲に収まるため、この出力回路は不要です。
OFF側では追加経路は定数選択によって未使用になります。

## 定数とテーブルの照合

`tools/gen_constants.py`は64行のexp係数を再生成し、C1/C2がC0と補正maskから
正確に復元できることを検査します。根系については`FP32Elementary`の係数と
照合します。また、各関数の全table行と到達し得る全残差について中間値を列挙し、
共有datapathの宣言幅に収まることも検査します。
さらに、根系の固定正規化・丸めcarryなしの条件と、低位判定による統合加算が
元のC0加算＋丸めに一致することを検査します。
ON側のrecipの追加丸め幅と、expの深いunderflowをzeroへ飽和できる値域も検査します。

```sh
make constants-check
make constants
```

係数、固定小数点位置、丸めbias、table例外、演算幅を変更した場合はquick testだけでなく、
該当する全数検査と単調性検査も再実行してください。

## 合成時の注意

合成トップは`FP32ExpRecipRsqrt`です。全体はclockなしの組合せ回路で、
パイプラインレジスタは含みません。

係数tableはSystemVerilogのunpacked定数配列で記述しています。合成器がこの構文を
直接扱えない場合は、同じ値を`function`と`case`で表すROMへ変換する必要があります。
変換時は係数と入出力がビット単位で一致することを確認してください。

## ライセンス

Copyright 2026 Ryota Shioya and Toru Koizumi

Apache License 2.0の下で公開します。詳細は[`../LICENSE`](../LICENSE)を参照してください。
