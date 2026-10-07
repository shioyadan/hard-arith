# FP64 FMA

IEEE 754 binary64の三入力に対して`a * b + c`を計算する、
合成可能なSystemVerilog組合せ回路です。積を途中で丸めずに加算し、
最後に一度だけ、入力信号で指定したモードへ丸めます。入出力subnormalを扱います。
既存のFP32 FMAと同じ構成を、binary64の仮数・指数幅へ拡張したものです。

- トップモジュール: `FP64FMA`
- インターフェース: clockなしの64-bit三入力・一出力、3-bit丸めモード入力
- 非正規化数: 入力・出力とも対応、FTZなし
- 精度仕様: 指定モードで正しい一回丸め、途中丸めなし
- 丸めモード: RNE・RTZ・RDN・RUP・RMMを実行時選択

## ファイル構成

```text
fp64_fma/
├── fp64_fma.sv
├── README.md
├── Makefile
└── test/
    ├── reference.hpp
    └── test.cpp
```

`fp64_fma.sv`だけが合成対象です。`test/reference.hpp`はMPFRによる独立参照、
`test/test.cpp`は特殊値・境界・固定seed乱数の検査です。係数テーブルや定数生成はありません。

## インターフェース

```systemverilog
module FP64FMA (
    input  wire [63:0] a,
    input  wire [63:0] b,
    input  wire [63:0] c,
    input  wire [2:0] rounding_mode,
    output wire [63:0] result
);
```

入出力はbinary64のbit patternです。clock、reset、valid、ready、例外フラグ、
NaN payload保持、演算opcodeはありません。入力保持・出力取り込みのレジスタは利用側で設けます。

```systemverilog
FP64FMA u_fma (
    .a(a), .b(b), .c(c),
    .rounding_mode(rounding_mode),
    .result(result)
);
```

## 合成時パラメータ

合成時パラメータはありません。FP64の積和、入出力subnormal対応、組合せ回路で固定です。
入出力幅・精度の変更やFTZへの切替は設定できません。丸めモードは実行時入力で指定します。

## 数値仕様

無限精度の`a * b + c`を指定モードで一度だけbinary64へ丸めた結果とのbit一致を仕様とします。
NaNはcanonical化し、例外フラグは出力しません。仕様と検証済み範囲は区別します。

| 入力または条件 | 出力 |
|---|---|
| 入力NaN、`0 * Inf`、無限積と逆符号の無限加数 | canonical quiet NaN `0x7ff8000000000000` |
| 上記以外の無限入力 | 積または加数の符号に従うInf |
| 有限値のoverflow | モードと符号に応じてInfまたは最大有限値。相殺は丸め前に扱う |
| 逆符号の厳密な相殺 | RDNだけ`-0`、他は`+0` |
| 同符号zero同士の和 | 同じ符号のzero |
| 入力subnormal | zeroへ置換せず計算する |
| 結果がunderflow領域 | 指定モードで丸めたsubnormalまたはzero。最小normalへの繰り上がりも扱う |
| 非zeroの結果がzeroへ丸まる | 結果の符号を保持したzero |

### 丸めモード

| `rounding_mode` | モード | 丸め方向 | 有限値のoverflow時の出力 |
|---|---|---|---|
| `3'b000` | RNE | 最近接、同点は偶数 | 符号付きInf |
| `3'b001` | RTZ | zero方向 | 符号付き最大有限値 |
| `3'b010` | RDN | 負の無限大方向 | 正は最大有限値、負は`-Inf` |
| `3'b011` | RUP | 正の無限大方向 | 正は`+Inf`、負は負の最大有限値 |
| `3'b100` | RMM | 最近接、同点は絶対値が大きい側 | 符号付きInf |

`101`・`110`・`111`は未対応の符号化としてcanonical NaNを返します。
CSR等から動的にモードを選ぶ機能は持たず、利用側で上記の値へ解決して入力します。

## 必要なツール

- Verilator 5.x
- C++17を扱えるC++コンパイラ
- MPFRとGMPのdevelopment library
- GNU MakeとBash

headerやlibraryが標準位置にない場合は`MPFR_CFLAGS`・`MPFR_LDFLAGS`で指定できます。
Verilator 5.020、MPFR 4.2.1で検証しています。

## テスト

公開リポジトリ直下から実行します。

```sh
make lint-fp64_fma
make test-fp64_fma
make -C fp64_fma stress
```

unit内では`make lint`・`make test`・`make stress`です。乱数組数は`RANDOM_CYCLES`で指定できます。
一括`make lint`・`make test`・`make clean`にも含まれます。
定数照合、三入力全数検査、専用の単調性検査は対象外です。

MPFR 4352 bitで積和を厳密に保持し、各モードのbinary64丸め結果を比較します。
有限入力の積の最小刻みは`2^-2148`、絶対値は`2^2048`未満であり、
加数を含めてもこの精度で全桁を保持できます。参照側で積和に丸めが起きないことも検査します。
RMMは隣接するbinary64値の厳密な中点と比較し、RTLのGRS処理は共有しません。
RNEはhostの`std::fma`とも照合し、参照実装を交差検査します。

通常検査は特殊値の直積、代表指数と全52仮数位置の相殺、整列・丸め境界、20万乱数組を含みます。
`stress`では相殺検査の指数fieldを全有限値0～2046へ広げ、指数境界を乗数一方の全有限指数と
他方の代表11指数で掃引し、乱数を100万組へ増やします。全指数の直積や全仮数の列挙ではありません。
各入力組を全5モードで検査し、特殊値の直積では予約符号化3種も確認します。
乱数seedは`0xf64f0a0123456789`です。

## 検証済み精度

2026-10-06に次を確認しました。通常・stressの件数は全5モードの合計です。

| 指標 | 通常検査 | stress検査 |
|---|---:|---:|
| MPFRとのbit比較 | 1,392,625件 | 32,800,985件 |
| bit不一致 | 0 | 0 |
| 予約符号化の検査 | 52,728件 | 52,728件 |
| 予約符号化のcanonical NaN不一致 | 0 | 0 |
| host RNEとの交差照合 | 278,525件 | 6,560,197件 |
| host RNEとの不一致 | 0 | 0 |
| lint | PASS | PASS |

subnormal、NaN・Inf、符号付きzero、overflow前の相殺、tieを含む標本・境界検査です。
これらの数値検査は三入力全`2^192`組合せの全数検査ではなく、以下の形式等価性検証とは区別します。
合成・gate検証などの評価状況は評価リポジトリで管理します。

### 形式等価性検証

2026-10-07、Berkeley HardFloat Release 1（RISCV specialization）を比較対象とする形式等価性検証により、
三入力の全`2^192`通りとRNE・RTZ・RDN・RUP・RMMの全5丸めモードの全組合せで、64-bit結果の一致を証明しました。
入出力subnormal、NaN・Inf・符号付きzero、overflow／underflowを含みます。

NaNはcanonical quiet NaN `0x7ff8000000000000`へ統一して比較します。対象は二値の組合せ回路であり、
例外フラグ、予約モード、X/Zを含むsimulation動作はHardFloatとの等価性の対象外です。
予約モードのcanonical NaN出力はDUTの契約として別途証明しています。
これは参照実装との等価性の証明で、IEEE 754規格そのものを独立に形式化した証明ではありません。

検証対象はcommit `9dcf776fb1a97a14b5316c6f6cf5deb76cd211bd`の`fp64_fma.sv`です。
RTLのSHA-256は`af0a0fa1c50673197a93c784af3bd9286a410f7041f9af98eabccddef3e06239`です。
証明はこのRTLに対するもので、後続のRTL変更には再検証が必要です。

FP32版の証明を引き継がず、元回路との対応を確認した乗算・整列の補題と、後段の入力領域分割を組み合わせ、
全入力を覆うことも確認しています。この形式等価性検証の比較用コード・外部原本・詳細な手順と証拠は
評価リポジトリで管理し、公開側には同梱しません。HardFloatは検証時の比較対象であり、公開RTLの依存物ではありません。

## アルゴリズム

### 基本的な考え方

FMAでは積の低位桁が相殺後に出力の上位へ現れるため、53×53 bitの積を106 bitのまま保持します。
加数の桁合わせを乗算と並列に進め、加減算後に正規化し、最後に一度だけ丸めます。

```text
入力の分類と指数・仮数の分離
  → 仮数の乗算と加数の桁合わせを並列に計算
  → 同じ桁位置で加減算
  → 先頭位置に合わせて正規化
  → 指定モードで一度だけ丸め、特殊値を選んで出力
```

指数fieldを`e`、fractionを`f`とし、`E=max(e,1)`、`M={e != 0,f}`と置くと、
有限入力の絶対値は`M * 2^(E-1075)`です。subnormal入力もこの格子で扱い、入力正規化は不要です。

`Ep=Ea+Eb-1023`を積の基準指数とし、積の下に3 bitを加えます。
この整数の1 bitは`2^(Ep-1130)`を表します。
加数は`Mc * 2^(Ec-Ep+55)`へ整列し、落ちるbitをstickyへまとめます。
和は符号を含む164 bitの2の補数表現です。

### 実装

1. 加数を`{Mc,110'b0}`から右へ`d=Ep-Ec+55`動かします。
   距離の下位4 bitは全幅の指数差と並列に計算します。`d<0`では微小な積を方向指定丸めにだけ反映して加数を返します。
2. 積が存在する下位109 bitとcarryを110 bitの加算で計算します。
   上位55 bitは加数だけからcarry伝播条件を先に作り、下位carryが確定するとXORで反映します。
   乗算と加算には演算子を使い、実装の選択を合成器へ任せます。
3. 下位108 bitの隣接XORを走査し、上端からの先頭距離を直接求めます。
   normal加数が上位に残る場合は整列距離とcarryから位置を求め、上位全域のLZCを避けます。
   上位subnormal加数には固定格子を使います。
4. 正規化の左shiftを段階的に行い、各段で保持窓を狭めます。
   subnormalの左shift上限は`Ep+54`です。`Ep < -54`では非zero加数はbypass済みで、
   残る極小積を符号・丸め方向に応じてzeroか最小subnormalへ丸めます。
5. 負の和はbit反転で`|sum|-1`として扱い、絶対値化の`+1`と丸めの増分を一つにまとめます。
   保持仮数53 bitとguard・round・stickyからモードを適用し、指数carryと特殊値を処理します。

| ブロック | 主な幅 |
|---|---|
| 仮数乗算 | 53×53 bit、積106 bit |
| 加数整列 | 53 bit仮数から163 bit |
| 下位積和 | carry込み110 bit |
| 上位補正 | 55 bit、下位109 bitと合わせて和164 bit |
| 先頭検出 | 下位108 bitの遷移、距離8 bit |
| 正規化 | 163→118→86→70→62→58→56→55 bit、別途sticky |
| 丸め | 保持仮数53 bit、結果54 bit |
| 出力選択 | fraction 52 bit、符号・指数12 bit |

## 合成時の注意

合成トップは`FP64FMA`です。`fp64_fma.sv`だけを入力し、clockなしの組合せ回路として扱います。
固定丸めモードでは`rounding_mode`を定数へ接続できます。
合成・gate検証は評価リポジトリで予備評価を行っています。電力・配置配線後の性能は未評価です。
面積・遅延は評価条件に依存するため、このREADMEでは規定しません。

## ライセンス

Copyright 2026 Ryota Shioya and Toru Koizumi

Apache License 2.0の下で公開します。詳細は[`../LICENSE`](../LICENSE)を参照してください。
