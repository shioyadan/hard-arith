# FP32 Inverse Square Root

IEEE 754 binary32のbit patternを入力し、逆数平方根`rsqrt(x)=1/sqrt(x)`を返す、
合成可能なSystemVerilog組合せ回路です。指数偶奇ごとの32区間一次初期値と
Newton反復1回を使い、正のnormal入力に対してfaithful roundingを行います。
第1段階の実装ではsubnormal入力をFTZとして扱います。

- トップモジュール: `FP32Rsqrt`
- インターフェース: clockなしの32-bit入出力
- subnormal入力: signed zeroとして扱う
- 精度: 正のnormal入力では厳密値を挟む二つのbinary32値のどちらか
- 単調性: `+0`から`+Inf`までの非負領域で単調非増加

## ファイル構成

```text
fp32_rsqrt/
├── fp32_rsqrt.sv
├── README.md
├── Makefile
├── test/
│   ├── exhaustive.cpp
│   ├── monotonic.cpp
│   ├── reference.c
│   └── tb_fp32_rsqrt.sv
└── tools/
    └── gen_constants.py
```

`fp32_rsqrt.sv`だけが合成対象です。`test/`はquick test、指数偶奇2通りの全仮数検査、
単調性検査、`tools/`は係数表の再生成・転記ミス検査に使います。

## インターフェース

```systemverilog
module FP32Rsqrt (
    input  wire [31:0] x,
    output wire [31:0] result
);
```

`x`と`result`はIEEE 754 binary32のbit patternです。clock、reset、valid、ready、
例外flag、NaN payload保持、動的な丸めモード入力はありません。

```systemverilog
FP32Rsqrt u_rsqrt (
    .x(x),
    .result(result)
);
```

## 数値仕様

正のnormal入力でのfaithful roundingは、無限精度の`1/sqrt(x)`を挟む直下・直上の
binary32値のどちらかを返すことを意味します。常にround-to-nearest-evenの結果を返す
correct roundingではありません。

| 入力 | 出力 |
|---|---|
| NaN | canonical quiet NaN `0x7fc00000` |
| `+Inf` | `+0` |
| `-Inf` | canonical quiet NaN `0x7fc00000` |
| `+0` / `-0` | `+Inf` / `-Inf` |
| 正負のsubnormal | signed zeroとして扱い、`+Inf` / `-Inf` |
| 正のnormal | faithful roundingしたnormal |
| 負のnormal | canonical quiet NaN `0x7fc00000` |
| `2^(2k)`である正のnormal | 厳密な`2^(-k)` |

正の有限normal入力から得られる逆数平方根の範囲はおよそ`[2^-64, 2^63]`なので、
出力は常にnormalです。したがって、この段階でFTZとなるのは入力subnormalだけであり、
subnormal出力の丸め処理は必要ありません。

このFTZ仕様では、subnormal入力に対する数学的なfaithful roundingを主張しません。
faithfulの適用範囲は正のnormal入力です。非負領域では入力を`+0`から`+Inf`へ増やすと、
出力は単調非増加となります。負の有限normalと`-Inf`はNaNなので単調性の対象外です。

## 必要なツール

- Verilator 5.x
- C++20、OpenMP、`unsigned __int128`を扱えるGCCまたはClang
- GNU Make
- Python 3

Verilator 5.020、GCC 13.3.0で動作を確認しています。

## テスト

リポジトリ直下から次を実行します。

```sh
make lint-fp32_rsqrt
make test-fp32_rsqrt
make exhaustive-fp32_rsqrt EXHAUSTIVE_THREADS=22
make monotonic-fp32_rsqrt
make constants-check-fp32_rsqrt
```

`fp32_rsqrt/`内では、それぞれ`make lint`、`make test`、`make exhaustive`、
`make monotonic`、`make constants-check`です。

`make test`は特殊値、FTZ境界、指数偶奇2通り×32区間の左端・中央・右端、固定seedの
20万乱数入力、20万点の単調性標本を検査します。参照値とfaithful上下限は、
次の式を満たす整数を128-bit整数比較で求めます。

```text
S = 2^23 + fraction
p = (input_exponent-127) mod 2
Z = sqrt(2^(71-p) / S)
```

ここで`Z`は基準出力binadeにおける24-bit出力仮数です。`floor(Z)`は
`r^2*S <= 2^(71-p)`を満たす最大整数として求め、直下値、直上値、RNE値を生成します。
参照モデルはRTLのテーブルやNewton演算に依存しません。

`make exhaustive`は、近似本体が異なる指数偶奇2通りについて全`2^23`仮数、合計
16,777,216入力をVerilated RTLへ与えます。別に全256指数fieldと代表9仮数、正負の
4,608入力を検査し、特殊値、FTZ、負数、指数再構成を確認します。これは全`2^32`
bit patternの列挙ではありません。

`make monotonic`は指数偶奇2通りについて全16,777,214隣接仮数を比較し、さらに非負領域の
全指数境界256組を比較します。近似本体が指数の値そのものではなく偶奇だけに依存することを
利用した縮約検査であり、全正normal bit pattern間の隣接組を個別に比較する検査ではありません。

## 検証済み精度

指数偶奇2通りの全仮数を使った独立整数参照モデルとVerilated RTLの照合結果は次です。

| 指標 | 結果 |
|---|---:|
| 検査した指数偶奇別仮数 | 16,777,216 |
| 代表指数・特殊値を含むRTL評価数 | 16,781,824 |
| RNE一致 | 16,607,192 |
| RNEとは異なるfaithful値 | 170,024 |
| RNE一致率 | 98.986578% |
| faithful違反 | 0 |
| RNEからの最大step数 | 1 |
| 観測最大絶対誤差 | 0.605060733284 ULP |
| 隣接仮数比較 | 16,777,214 |
| 指数境界比較 | 256 |
| 単調性違反 | 0 |

これは全仮数の列挙検査であり、形式証明や全`2^32` bit patternの個別列挙ではありません。

## アルゴリズム

### 基本的な考え方

正のnormalなbinary32入力は、`[1,2)`の仮数`m`と非バイアス指数`E`を使って表せます。

```text
x = m * 2^E
```

逆数平方根では指数を単純に反転するだけでなく半分にする必要があります。そこで`E`を
偶数部分`2q`と偶奇`p`へ分けます。

```text
E = 2q+p,  p in {0,1}
t = m * 2^p

1/sqrt(x) = 2^(-q) * 1/sqrt(t)
```

この式から、計算を二つに分離できます。

- 2の累乗部分は、指数を半分にして符号を反転した`2^(-q)`として作る
- 残った仮数部分についてだけ`1/sqrt(t)`を近似する

`p=0`なら`1 <= t < 2`、`p=1`なら`2 <= t < 4`です。したがって、広い入力範囲全体を
近似する必要はなく、二つの有限区間だけを扱えばよくなります。指数の偶奇ごとに係数を
持つ理由は、奇数指数に含まれる`1/sqrt(2)`を仮数近似側へ吸収するためです。

#### `1/sqrt(t)`の計算全体

本実装は次の順に仮数部を計算します。

1. 仮数`m`の上位5 bitで`[1,2)`を32分割し、指数偶奇と合わせて64行から係数を選ぶ。
2. 区間ごとの切片と差分を使う一次補間から、初期値`y0 ~= 1/sqrt(t)`を作る。
3. 残差`e0=t*y0^2-1`を、差を取る前に丸めず正確なsigned modulo値として作る。
4. Newton反復`y1=y0*(1-e0/2)`を1回行い、初期誤差を二乗する。
5. `2*y1`をbinary32仮数へ丸め、`2^(-q)`から導いた指数と組み合わせる。

#### 区分線形初期値が有効な理由

基準値`c`の近くで`z=c+r`とすると、逆数平方根は次のように展開できます。

```text
1/sqrt(z) = 1/sqrt(c)
            - r/(2*c^(3/2))
            + 3*r^2/(8*c^(5/2)) + ...
```

定数項と一次項までで近似したとき、最初に省略される誤差は`O(r^2)`です。一つの直線で
区間全体を扱う代わりに幅`h=1/32`へ分割すれば、各区間の一次近似誤差は`O(h^2)`へ
小さくなります。ここでの展開式は区分線形近似が有効な理由を示すものであり、RTLが
Taylor係数をそのまま計算するわけではありません。

実際には各区間の両端を結ぶ弦を作り、弦が持つ一方向の相対誤差を正負へ中心化した直線を
使います。区間左端の値を`A[p][i]`、右端までの減少量を`Delta[p][i]`、11-bit区間内位置を
`u`とすると、RTLの初期値は次です。

```text
y0_q16 = A[p][i] - floor(Delta[p][i] * u / 2^11)
```

#### Newton反復で誤差を二乗する

`F(y)=1/y^2-t=0`へNewton法を適用すると、通常の逆数平方根反復が得られます。

```text
y_next = y * (3-t*y^2) / 2
```

初期残差を`e0=t*y0^2-1`と書けば、本実装で使う形になります。

```text
y1 = y0 * (1-e0/2)
```

反復後の二乗残差は厳密に次の形です。

```text
t*y1^2-1 = -3*e0^2/4 + e0^3/4
```

一次近似の初期誤差が`O(h^2)`なので、理想的なNewton反復後は`O(h^4)`になります。
この誤差二乗により、初期表自体をbinary32の最終精度まで大きくせず、64行の小さな
一次表と1回の補正でfaithful roundingに必要な精度を得ます。

#### 零点付近のNewton残差

Newton残差`e0=t*y0^2-1`は、`y0=1/sqrt(t)`で零になります。零点付近で近い二数を
引く前に積の下位bitを捨てると、その丸め誤差が補正値へ直接現れます。

本実装では`m*y0^2`をQ55の全精度で作り、必要なら指数偶奇に応じて1 bit左shiftしてから、
`1.0`との差を下位44 bitのsigned modulo値として正確に取り出します。Q55の`1.0`は
`2^55`であり、`2^55 mod 2^44=0`なので、積の下位44 bitを二の補数として解釈できます。
全入力で残差がsigned 44 bitへ収まることを生成scriptで確認しています。残差を得た後でのみ、
Newton補正乗算に不要な下位bitを削ります。

#### 出力仮数と指数の正規化

`y1=1/sqrt(t)`は`(0.5,1]`にあるため、通常は`2*y1`を`[1,2)`のbinary32仮数にします。
このとき出力の基準biased exponentは`126-q`です。入力のbiased exponentを`e_field`とすると、
RTLでは次の整数式だけで求められます。

```text
base_exponent = (380-e_field-(e_field mod 2)) / 2
```

`p=0`かつ`m=1`、すなわち入力が`2^(2k)`なら`y=1`です。この場合は仮数近似をbypassし、
基準指数を1増やした厳密な`2^(-k)`を返します。近似結果が丸めによって`2.0`へ繰り上がる
場合も、同じように仮数を`1.0`、指数を1増やしてpackします。

### 実装

#### 1. 指数偶奇別32区間の誤差中心化初期値

仮数fractionの上位5 bitを区間番号、続く11 bitを区間内位置として使い、下位7 bitは
初期補間には使いません。`p=0`の32行は`1/sqrt(m)`、`p=1`の32行は
`1/sqrt(2m)`を近似します。切片は16-bit unsigned Q16、区間内の切片差もQ16ですが、
最大値が10 bitへ収まるため10-bitで保持します。

連続関数の弦について、最大相対誤差点は区間端`a,b`に対して次の位置です。

```text
x_max = (a+sqrt(a*b)+b)/3
```

両端の相対誤差0と区間内の正の最大相対誤差が同じ大きさで正負になるよう弦全体を縮小し、
その後Q16へ量子化します。係数の生成式は`tools/gen_constants.py`を正本とします。

#### 2. signed modulo残差

初期値から次の積を作ります。

```text
seed_square = y0*y0
seed_product = m*seed_square
e0 = (seed_product << p)-1
```

`m`は24-bit Q23、`y0^2`は32-bit Q32なので積は56-bit Q55です。指数偶奇を反映した
57-bit積の下位44 bitをsigned Q55として使います。全補間bucketの両端を調べた範囲は
`-3,676,004,757,504`から`+5,536,289,957,432`、実数では約
`-1.02030e-4`から`+1.53663e-4`であり、signed 44 bitに収まります。

#### 3. 量子化したNewton補正と最終丸め

補正乗算ではseedの下位1 bitを落としてQ15、残差の下位26 bitを落としてQ29とし、
signed 16×18 bit積を使います。積をQ32の`y0*e0/2`へ変換してseedから引きます。

```text
y1_q32 = (y0_q16 << 16) - correction_q32 + 128
```

`2*y1`をQ23仮数へ落とす位置での0.5 LSBに相当する`+128`を加えます。係数、量子化、
補正幅、biasを含む構成全体を指数偶奇2通りの全仮数検査で調整しています。

#### 幅の選定根拠

区分線形初期値と厳密なNewton演算だけを仮定した事前評価では、区間数ごとの保守的な
反復後誤差は次でした。値は正規化済みbinary32出力のULPへ換算しています。

| 各指数偶奇の区間数 | 理想Newton後の最大誤差 |
|---:|---:|
| 8 | 約10.637 ULP |
| 16 | 約0.747 ULP |
| 32 | 約0.0496 ULP |
| 64 | 約0.00320 ULP |

16区間は理想計算だけなら1 ULP内ですが、テーブル量子化、区間内位置の省略、Newton補正の
幅削減、最終丸めに使える余裕が小さくなります。64区間は余裕を増やす一方で表が倍になります。
初期実装では幅削減後もfaithfulと単調性を保てる中間点として、各偶奇32区間を採用しました。

#### 固定小数点形式

`Qn`は格納整数に`2^-n`を掛けた値を表す固定小数点表現という意味です。

| 信号・定数 | 幅 | 形式 | 役割 |
|---|---:|---|---|
| `x_sig` | 24 | unsigned Q23 | 入力normal仮数`m` |
| `A[p][i]` | 16 | unsigned Q16 | 誤差中心化した区間左端の切片 |
| `Delta[p][i]` | 10 | unsigned Q16 | 区間内のQ16切片差 |
| `residual` | 11 | unsigned整数 | 区間内位置の上位11 bit |
| `interpolation_product` | 21 | unsigned Q16 | `Delta[p][i]*residual` |
| `rsqrt_seed` | 16 | unsigned Q16 | 区分一次初期値`y0` |
| `seed_square` | 32 | unsigned Q32 | `y0^2` |
| `seed_product` | 56 | unsigned Q55 | `m*y0^2` |
| `scaled_seed_product` | 57 | unsigned Q55 | `t*y0^2` |
| `error_excess` | 44 | signed Q55 | signed moduloで表す`t*y0^2-1` |
| `correction_seed` | 15 | unsigned Q15 | seedの下位1 bitを省いた値 |
| `correction_seed_signed` | 16 | signed Q15 | 正値のseedを1 bit拡張した値 |
| `error_high` | 18 | signed Q29 | errorの下位26 bitを省いた値 |
| `correction_product` | 34 | signed Q44 | 量子化した`y0*e0` |
| `correction` | 21 | signed Q32 | `y0*e0/2`の補正量 |
| `rsqrt_q32` | 34 | signed Q32 | Newton反復後の`1/sqrt(t)` |
| `normalized_sig` | 25 | unsigned Q23 | 正規化済み`2/sqrt(t)` |

#### 主な演算資源

| ブロック | 主な幅 | 役割 |
|---|---:|---|
| 切片表 | 64×16 bit | 指数偶奇別・誤差中心化した区間左端値 |
| 差分表 | 64×10 bit | 区分一次補間の傾き |
| 補間乗算 | 10×11 bit | 区間内の一次補正 |
| seed平方 | 16×16 bit | Newton残差用の`y0^2` |
| seed積 | 24×32 bit | signed modulo Newton残差の生成 |
| Newton補正乗算 | signed 16×18 bit | 量子化した`y0*e0` |
| Newton再構成 | signed 34 bit加減算 | seed、補正、最終biasの合成 |
| 指数演算 | 9 bit減算と右shift | 指数の半減と符号反転 |

係数表の格納量は切片1,024 bit、差分640 bit、合計1,664 bitです。論理的な表の大きさであり、
合成後の実装は合成器のROM推論や論理最適化に依存します。

## 定数と係数表の照合

`tools/gen_constants.py`はPython `Decimal`で指数偶奇別64行の誤差中心化直線を作り、
RTLに格納したQ16切片、Q16差分、主要な幅・slice、最終biasと照合します。

```sh
make constants-check
make constants
python3 tools/gen_constants.py --check fp32_rsqrt.sv --analyze
```

`--analyze`は全補間bucketの両端を整数演算で走査し、Newton前残差の最小値、最大値、
必要signed幅を表示します。係数、区間数、固定小数点幅、積のbit抽出位置、Newton biasを
変更した場合は、quick testだけでなく`make exhaustive`と`make monotonic`を再実行してください。

## subnormal入力対応を追加する場合

現在の近似本体はnormal仮数だけを受け取ります。gradual underflowへ拡張する場合は、
近似表とNewton反復を再利用しつつ、subnormal入力のleading-zero count、左正規化、
正規化後の拡張指数を追加する必要があります。負のsubnormalは正規化後に負数となるため
qNaNへ変わり、現在のsigned-zero FTZ規約とは特殊値仕様も変わります。

## 合成時の注意

合成トップは`FP32Rsqrt`です。全体はclockなしの組合せ回路で、パイプラインレジスタは
含みません。

二つの64要素テーブルはSystemVerilogのunpacked定数配列で記述しています。合成器がこの構文を
直接扱えない場合は、同じ値を`function`と`case`で表すROMへ変換する必要があります。
変換時は定数照合とゲートテストで入出力がビット単位に一致することを確認してください。

## ライセンス

Copyright 2026 Ryota Shioya and Toru Koizumi

Apache License 2.0の下で公開します。詳細は[`../LICENSE`](../LICENSE)を参照してください。
