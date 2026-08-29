# FP32 Sin/Cos Pi

IEEE 754 binary32のbit pattern `x`と演算選択を入力し、`sin(pi*x)`または
`cos(pi*x)`を一つの出力へ返す、合成可能なSystemVerilog組合せ回路です。
精度を優先する`FP32SinCosPi`と、絶対誤差を固定して小型化した
`FP32SinCosPiLite`を併置しています。

| 公開トップ | 精度条件 | 構成 |
|---|---|---|
| `FP32SinCosPi` | faithful rounding、RNE参照から最大1 ULP | Q31位相、三次近似、小入力補正 |
| `FP32SinCosPiLite` | 絶対誤差 `<= 4*2^-23` | Q23位相、区間ごとに最適化した二次近似 |

- `select_cos=0`: `sin(pi*x)`
- `select_cos=1`: `cos(pi*x)`
- clockなし、binary32入力1本、選択1 bit、binary32出力1本
- 共通の位相縮約、table、多項式、packerをsinとcosで共有

## インターフェース

```systemverilog
module FP32SinCosPi (
    input  wire [31:0] x,
    input  wire        select_cos,
    output wire [31:0] result
);

module FP32SinCosPiLite (
    input  wire [31:0] x,
    input  wire        select_cos,
    output wire [31:0] result
);
```

sinとcosを同時には出力しません。`select_cos`で選んだ一方だけを`result`へ返すため、
二つの出力を常に計算する構成より、後段の近似回路を共有しやすくしています。

## 数値仕様

| 入力または条件 | `sin(pi*x)` | `cos(pi*x)` |
|---|---|---|
| NaN、`+Inf`、`-Inf` | canonical quiet NaN `0x7fc00000` | canonical quiet NaN `0x7fc00000` |
| `+0` | `+0` | `+1` |
| `-0` | `-0` | `+1` |
| 整数 | 厳密なzero | 厳密な`+1`または`-1` |
| 半整数 | 厳密な`+1`または`-1` | 厳密なzero |
| その他の有限値 | `sin(pi*x)`の近似値 | `cos(pi*x)`の近似値 |

周期境界のzeroは片側極限と整合する符号を保持します。例えば、`sin(pi*1)`は`-0`、
`sin(pi*(-1))`は`+0`です。例外flag、NaN payload、動的丸めmodeには対応しません。

`FP32SinCosPi`は入出subnormalを保持し、厳密値を挟む直下・直上の
binary32値のどちらかを返すfaithful roundingを目標とします。
`FP32SinCosPiLite`は絶対誤差だけを規定するため、zero近傍では非zeroの厳密値に
signed zeroを返すことがあり、faithful roundingや単調性は仕様に含めません。
検証範囲と観測した最大誤差は後の表にまとめます。

## アルゴリズム

### 共通の構造

sinとcosを別々の多項式で計算するのではなく、cosを位相が0.5ずれたsinとして扱います。

```text
cos(pi*x) = sin(pi*(x+0.5))
```

さらに周期性と対称性を使えば、どちらの演算も`0 <= u <= 0.5`にある一つの
`sin(pi*u)`へ変換できます。実装の流れは次のとおりです。

```text
1. |x| mod 2を固定小数点の位相pへ変換する
2. cosを選んだ場合だけpへ0.5を正確に加える
3. 周期性と対称性で0 <= u <= 0.5へ縮約し、結果の符号を決める
4. uに最も近いtable中心cを選び、d=u-cを作る
5. sin(pi*(c+d))をcまわりの多項式で近似する
6. 固定小数点結果をbinary32へ丸める
```

この構造では、sin/cosの選択に浮動小数点加算器を使いません。`0.5`の加算は
位相bitへの定数加算になり、その後のtable、多項式、packerを共有します。
faithful版はQ31と三次式、Lite版はQ23と二次式を使います。

### faithful版の位相縮約

normal入力を次の整数仮数`M`と指数`E`で表します。

```text
|x| = M*2^(E-23),  2^23 <= M < 2^24
```

`E >= -8`では、Q31位相は次の整数演算で正確に得られます。

```text
p = (M << (E+8)) mod 2^32
```

Q31の32 bitを`0 <= p < 2`として読むため、下位bitを取るだけで周期2の剰余になります。
`E >= 24`のbinary32はすべて偶数整数なので位相は0です。cos選択時は、この位相へ
Q31の`0.5`である`0x40000000`を加えます。

次に、位相の整数側で結果符号を決め、周期内の小数部`r`を対称性で折り返します。

```text
u = min(r, 1-r)
0 <= u <= 0.5
```

### faithful版のtable中心まわりの三次近似

縮約後の`u`に最も近い65点の中心を選びます。

```text
c = j/128,  0 <= j <= 64
d = u-c
|d| <= 2^-8
```

中心間隔を小さくすることで、多項式へ入る差分`d`を0に近づけています。
各中心のまわりで次の式を使います。

```text
sin(pi*(c+d))
  ~= A[c]+d*(B[c]+d*(C[c]+d*D[c]))

A[c] =  sin(pi*c)
B[c] =  pi*cos(pi*c)
C[c] = -pi^2*sin(pi*c)/2
D[c] = -pi^3*cos(pi*c)/6
```

可変乗算はHorner形式の3回です。中心ごとに`A/B/C/D`をtableへ置くことで、
一つの多項式へ広い範囲を直接与える場合より、必要な次数と乗算幅を抑えています。

### faithful版の小さいsin入力

`|x| < 2^-8`では、Q31位相へ変換した時点で元のbinary32仮数をすべて保持できません。
cosは0付近で傾きが0なのでQ31位相でも必要精度を保てますが、sinは相対精度を失います。
そこでsinだけは次の形で計算します。

```text
sin(pi*x) = x*(sin(pi*x)/x)
```

`E=-9..-14`では`pi-sin(pi*x)/x`を、指数ごとに16区間の一次補間で求めます。
それより小さい入力では補正が1 ULPより十分小さくなるため、係数に`pi`を使います。
一次補間積と最後の`x`との積は通常経路の第1・第3乗算器を共有するため、選択可能にした
ことで小入力専用の大きな乗算器は増えません。subnormal入力は先頭1を検出して正規化し、
共通packerでsubnormal出力までround-to-nearest-evenします。

### faithful版の固定小数点幅

| 値 | 表現 | 幅 |
|---|---|---:|
| 位相`p`、縮約値`u` | Q31 | 32 / 31 bit |
| table差分`d` | signed Q31 | 24 bit |
| `A[c]` | Q32 | 33 bit |
| `B[c]` | Q25 | 27 bit |
| `C[c]` | signed Q16 | 20 bit |
| `D[c]` | signed Q7 | 11 bit |
| 小入力補正の基点 / 差分 | Q24 | 11 / 7 bit |
| 最終乗算積 | signed、通常経路はQ56 | 53 bit |

各値の実際の範囲とfaithful性を確認し、演算ごとに必要なbitだけを残しています。三つの
乗算器は通常経路で順に24x11、24x20、25x28 bitとなり、小入力経路とも共有します。
65行の主tableは1行91 bit、小入力補正tableは96行で1行18 bitです。`c=0`では
`A[c]=0`となるため、Q32へ早く丸めず、最後のQ56積をそのままpackerへ渡して
zero近傍の相対精度を保ちます。

### Lite版の小型化

Lite版も同じ位相縮約を使いますが、絶対誤差は値の大小によらず一定なので、
zero近傍の相対精度を保つ小入力補正を省き、位相をQ23へ最近接丸めします。
`0 <= u <= 0.5`を幅`2^-7`の64区間へ分け、各区間の中央
`c=(j+0.5)/128`との差`d=u-c`を作ります。このとき`|d| <= 2^-8`です。
各区間では次の二次式を使います。

```text
sin(pi*(c+d)) ~= A[c]+d*(B[c]+d*C[c])
```

係数はTaylor係数を個別に丸めるのではなく、Q23位相への丸め、係数と中間値の量子化、
binary32への丸めを含めた区間内の最大絶対誤差が小さくなるように生成時に調整します。
`A/B/C`はそれぞれQ24/Q15/Q5、tableは1行51 bitです。可変乗算は
16x9 bitと16x18 bitの2回となり、faithful版の三次項、小入力table、
subnormal用packerを削除しています。

## ファイル

| ファイル | 内容 |
|---|---|
| `fp32_sincospi.sv` | RTL、table、公開トップ`FP32SinCosPi` |
| `fp32_sincospi_lite.sv` | 小型RTL、table、公開トップ`FP32SinCosPiLite` |
| `tools/gen_constants.py` | 両実装のtableと小入力補正tableの生成・照合 |
| `test/tb_fp32_sincospi.sv` | directed、指数境界、固定seed random test |
| `test/exhaustive.cpp` | 小入力補正、正subnormal、主近似区間の全数検査 |
| `test/tb_fp32_sincospi_lite.sv` | Lite版のdirected、指数境界、固定seed random test |
| `test/exhaustive_lite.cpp` | Lite版の全Q23位相と丸め区間両端の検査 |
| `test/reference.c` | binary128参照値、faithful境界、絶対誤差 |

## 検証済み精度

| 検査 | 評価数 | RNE一致 | faithful違反 | 最大差 | 隣接単調性違反 |
|---|---:|---:|---:|---:|---:|
| directed、指数境界、20万乱数のsin/cos | 400,742 | 390,647 | 0 | 1 ULP | 対象外 |
| 小入力補正、正subnormal、主近似の全table中心を覆う区間 | 75,497,471 | 68,919,270 | 0 | 1 ULP | 0 |

Lite版は別の絶対誤差条件で検査します。

| 検査 | 評価数 | 絶対誤差違反 | 観測最大絶対誤差 | table境界の微小な逆行 |
|---|---:|---:|---:|---:|
| directed、指数境界、20万乱数のsin/cos | 400,744 | 0 | `3.449444798*2^-23` | 対象外 |
| 全Q23縮約位相と、入力位相の丸め区間両端 | 4,194,305位相 | 0 | `3.673060963*2^-23` | 2,441 |

quick testの参照値はbinary128で計算します。faithful版の全数検査は対象が正の有限入力のsinに限られ、
binary32判定に対して十分広い精度を持つ`long double`を高速oracleとして使います。
Lite版は対称性でsin/cosが共有する全Q23縮約位相を走査し、それぞれに対して丸め前の
位相が取り得る区間の両端を`long double`で検査します。関数が平坦になる1付近では
中間値の丸めにより最大3 ULPの微小な逆行が2,441箇所あります。これはLite版の
絶対誤差条件内ですが、単調性が必要な用途ではfaithful版を使います。いずれも形式証明や
精度保証付きの計算機援用証明ではありません。

## 検証

```sh
make lint
make test
make exhaustive
make constants-check
```

`make test`は両実装に対し、NaN、無限大、signed zero、subnormal、経路境界、整数、半整数、
位相が失われ始める大入力、各2の累乗、および固定seedの20万乱数をsin/cosの両方で検査します。
`make exhaustive-faithful`は小入力補正tableを使う正のnormal入力50,331,648個、正のsubnormal入力
8,388,607個、主近似の`2^-8 <= x < 2^-7`と`0.5 <= x < 1`を列挙します。後者は対称性に
より縮約後の`0 < u <= 0.5`全域を覆います。負入力、cos、全`2^32` bit patternの
全数検査ではありません。`make exhaustive-lite`は上記の全Q23位相検査を実行し、
`make exhaustive`は両方を実行します。
