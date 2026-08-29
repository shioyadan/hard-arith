# FP32 Square Root

IEEE 754 binary32のbit patternを入力し、平方根`sqrt(x)`を返す、合成可能な
SystemVerilog組合せ回路です。正のnormal入力では、平方根と逆数平方根の二初期値を
区分線形補間で作り、1回補正してfaithful roundingを実現します。第1段階の実装では
subnormal入力をFTZとして扱います。

- トップモジュール: `FP32Sqrt`
- インターフェース: clockなしの32-bit入出力
- subnormal入力: signed zeroとして扱う
- 精度: 正のnormal入力では厳密値を挟む二つのbinary32値のどちらか
- 単調性: `+0`から`+Inf`までの非負領域で単調非減少

## ファイル構成

```text
fp32_sqrt/
├── fp32_sqrt.sv
├── README.md
├── Makefile
├── tools/
│   └── gen_constants.py
└── test/
    ├── exhaustive.cpp
    ├── reference.c
    └── tb_fp32_sqrt.sv
```

`fp32_sqrt.sv`だけが合成対象です。`tools/gen_constants.py`は二初期値の接線係数を
高精度Decimalで再生成し、RTLと照合します。`test/`はquick test、指数偶奇2通りの
全仮数検査、単調性検査に使います。

## インターフェース

```systemverilog
module FP32Sqrt (
    input  wire [31:0] x,
    output wire [31:0] result
);
```

`x`と`result`はIEEE 754 binary32のbit patternです。clock、reset、valid、ready、
例外flag、NaN payload保持、動的な丸めモード入力はありません。

```systemverilog
FP32Sqrt u_sqrt (
    .x(x),
    .result(result)
);
```

## 数値仕様

正のnormal入力でのfaithful roundingは、無限精度の`sqrt(x)`を挟む直下・直上の
binary32値のどちらかを返すことを意味します。常にround-to-nearest-evenを返す
correct roundingではありません。

| 入力 | 出力 |
|---|---|
| NaN | canonical quiet NaN `0x7fc00000` |
| `+Inf` | `+Inf` |
| `-Inf` | canonical quiet NaN `0x7fc00000` |
| `+0` / `-0` | `+0` / `-0` |
| 正負のsubnormal | signed zeroとして扱い、`+0` / `-0` |
| 正のnormal | faithful roundingしたnormal |
| 負のnormal | canonical quiet NaN `0x7fc00000` |
| `2^(2k)`である正のnormal | 厳密な`2^k` |

正のnormal入力の平方根はおよそ`[2^-63, 2^64)`にあり、結果は常にnormalです。
したがって、この段階でFTZとなるのは入力subnormalだけであり、subnormal出力の
丸め処理は必要ありません。

このFTZ仕様では、subnormal入力に対する数学的なfaithful roundingを主張しません。
faithfulの適用範囲は正のnormal入力です。非負領域では入力を`+0`から`+Inf`へ
増やしたとき、出力は単調非減少となります。負の有限normalと`-Inf`はNaNなので
単調性の対象外です。

## 基本的な考え方

正のnormal入力を、`m`を`[1,2)`の仮数、`E`を非バイアス指数として表します。
指数を偶数部分`2q`と偶奇`p`へ分けると、平方根は次の形になります。

```text
x = m * 2^E
E = 2q+p,  p in {0,1}
t = m * 2^p,  t in [1,4)
sqrt(x) = 2^q * sqrt(t)
```

2の累乗部分は指数を半分にするだけです。実際に近似する必要があるのは、有限範囲
`[1,4)`へ縮小した`sqrt(t)`だけです。本実装は最初に`sqrt(t)`の初期値`s0`と
`1/sqrt(t)`の初期値`y0`を同時に作り、次の1回補正を行います。

```text
e  = s0^2-t
s1 = s0-e*y0/2
```

`y0`が厳密な`1/s0`なら、これは平方根に対するNewton法
`s1=(s0+t/s0)/2`と同じです。逆数平方根初期値を別に用意することで、除算器を使わず、
小さい固定小数点乗算で補正できます。

## 二初期値の区分線形補間

指数偶奇ごとに仮数範囲を16区間へ分けます。各区間では中央点における接線を使い、
左端切片と区間全体の差分をQ16で保持します。論理的には次の二つのseed表です。

- `sqrt(t)`用: Q16切片17 bit、差分12 bit
- `1/sqrt(t)`用: Q16切片16 bit、差分11 bit

RTLでは切片と差分を別配列にしているため定数配列は四つあります。入力上位4仮数bitと
指数偶奇で32行を選び、区間内位置との小さい乗算で補間します。接線近似では中心で誤差が0となり、
区間内の一次変化を表で吸収するため、補間後の誤差は主に二次以上の小さい成分になります。

## 混合精度の1回補正

5 nsだけでなく短い遅延制約でも面積を保つため、各経路を必要な精度へ個別に縮めています。

- sqrt初期値: Q16係数をQ13へ丸め、8-bit区間内位置で補間
- invsqrt初期値: Q14、7-bit区間内位置で補間
- 残差`e=s0^2-t`: 相殺後に必要なsigned 24 bitだけを生成
- 補正積: 残差下位7 bitを除いた17x14 bit相当
- 最終値: Q49へ再構成し、11/32 ULPの固定biasを加えてbinary32仮数化

上位が一致して相殺する`s0^2`と`t`は、低位24 bitだけを減算してsigned残差を作ります。
また、補正へ影響しない残差下位bitを乗算前に除くことで、乗算器を縮小しています。
固定biasはRNEを行うためではなく、切り捨てと近似の誤差分布をfaithful範囲の中央へ寄せるためです。

## 必要なツール

- Python 3.9以上
- Verilator 5.x
- C++20、OpenMPを扱えるGCCまたはClang
- GNU Make

Verilator 5.020、GCC 13.3.0で動作を確認しています。

## テスト

リポジトリ直下から次を実行します。

```sh
make constants-check-fp32_sqrt
make lint-fp32_sqrt
make test-fp32_sqrt
make exhaustive-fp32_sqrt EXHAUSTIVE_THREADS=22
make monotonic-fp32_sqrt EXHAUSTIVE_THREADS=22
```

`fp32_sqrt/`内では、それぞれ`make constants-check`、`make lint`、`make test`、
`make exhaustive`、`make monotonic`です。`make monotonic`は単調性を含む全数検査を実行します。

`make test`は特殊値、FTZ境界、全指数fieldの代表仮数、固定seedの20万乱数入力、
20万点の単調性標本を検査します。参照値はRTLから独立に、24-bit整数仮数から48-bit以内の
被開平数を作り、64-bit整数上の二分探索で厳密な直下値と直上値、RNE値を求めます。

`make exhaustive`は近似本体が異なる指数偶奇2通りについて全`2^23`仮数、合計
16,777,216入力をVerilated RTLへ与えます。同じ出力列の全隣接仮数と全253指数境界、
特殊値も検査します。指数偶奇と仮数へ縮約できる全正規化仮数を網羅しますが、形式証明や
全`2^32` bit patternの直接列挙ではありません。

## 検証済み精度

指数偶奇2通りの全仮数を使った独立整数参照モデルとVerilated RTLの照合結果は次です。

| 指標 | 結果 |
|---|---:|
| 検査した指数偶奇別仮数 | 16,777,216 |
| RNE一致 | 14,721,148 |
| RNEとは異なるfaithful値 | 2,056,068 |
| faithful違反 | 0 |
| RNEからの最大step数 | 1 |
| 観測最大絶対誤差 | 0.955862419044 ULP |
| 隣接仮数・指数境界比較 | 16,777,467 |
| 単調性違反 | 0 |

これは有限入力集合の全数simulationによる確認であり、形式証明ではありません。
