# 共通Hornerカーネルの幅・積和統合候補

`generate.py`で固定した基準RTLから比較候補を生成します。
公開トップには`delta18-both`（18-bit残差と両段の加算統合）を採用しました。
比較元は公開repositoryのcommit `bc9b4f22271a1eb93012c62141401e7581e05893`から
`git show`で取得し、SHA256を検査します。通常の合成・testはこの履歴に依存しません。
数値仕様は[公開仕様](../../README.md#数値仕様)と同じです。入出力FTZ、特殊値、
無効・不正opのcanonical qNaN、六つの機能選択parameter、単調性を維持します。
exp2／recip／rsqrt／sqrtは最大1 RNE step、log2は最大2 stepまたは絶対誤差
`4 * 2^-23`以下、sinpi／cospiは同じ絶対誤差以下です。
共通packerのRNEと、演算全体の許容誤差を区別します。

| 候補 | 変更 |
|---|---|
| `baseline` | 基準RTLとbyte一致 |
| `delta18` | Q24残差の正端点131072を131071へclampし、乗算器入力を18 bitへ縮小 |
| `inner` | C1加算を内側の積・丸めbiasと一つの式へ統合 |
| `outer` | C0加算を外側の積・丸めbiasと一つの式へ統合 |
| `both` | 内側・外側をともに統合 |
| `delta18-inner`／`delta18-outer`／`delta18-both` | 18-bit化との組合せ |

`inner`と`outer`は途中の丸め位置を維持する同値変形です。非exp2のC0はQ27整数で
4の倍数であることを利用し、外側のQ25丸めを維持します。候補RTLのbit一致と、
独立高精度参照による精度検査は別に行います。

18-bit化を含む候補ではexp2の出力bit列が変わります。生成器は既存の量子化cell上下限からC0の許容域を
求め、行内・隣接行・63→0の単調性を満たす中で、基準からの変更総量が最小のC0列を選びます。
C1/C2とtable幅は変えません。binary64による係数選別だけでは合格とせず、既存のRTL全数test
（exp2全入力とbinary128境界再判定、および他関数の縮約検査）で再検証します。

```sh
python3 experiments/kernel_opt/generate.py --output build/kernel-opt
python3 experiments/kernel_opt/generate.py --output build/kernel-opt --check
python3 experiments/kernel_opt/test_generator.py
python3 experiments/kernel_opt/verify.py --sources build/kernel-opt \
  --output build/kernel-opt-verification --jobs 2 --threads 8
python3 experiments/kernel_opt/configs.py --sources build/kernel-opt \
  --output build/kernel-opt-configs --jobs 2
make test RTL="$PWD/build/kernel-opt/delta18-both.sv" BUILD_DIR="$PWD/build/kernel-opt/test"
make exhaustive RTL="$PWD/build/kernel-opt/delta18-both.sv" \
  BUILD_DIR="$PWD/build/kernel-opt/test" \
  EXHAUSTIVE_BUILD_DIR="$PWD/build/kernel-opt/exhaustive" EXHAUSTIVE_THREADS=8
make test-configs RTL="$PWD/build/kernel-opt/delta18-both.sv" \
  CONFIG_BUILD_DIR="$PWD/build/kernel-opt/configs"
```

commandは`fp32_elementary/`を基準にします。生成物とmanifestは`build/`以下へ置きます。
`--check`はC0選別も再計算し、RTLとmanifestを照合します。候補の定数照合にはこのcommandを
使い、公開トップ用の`constants-check`は公開トップに対して別途実行します。
生成器は基準SHA256の異なるRTLを拒否し、既存候補を無条件に上書きしません。
この実験の再生成には上記commitを含むGit履歴が必要です。生成器更新前のmanifestは
測定時点の証拠として残し、新しい生成器では別の出力directoryを指定してください。

`verify.py`は全候補のlint・通常testに加え、基準と候補を併置した検証専用wrapperを生成し、
縮約走査とexp2全入力走査の各入力で数値仕様とbit一致を検査します。
18-bit候補のexp2だけは基準との一致を要求しません。全入力走査はexp2が対象で、
他関数は仮数・位相の縮約全数と全指数の境界標本です。形式証明ではありません。
