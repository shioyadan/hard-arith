# Copyright 2026 Ryota Shioya and Toru Koizumi
# SPDX-License-Identifier: Apache-2.0
import unittest

import mpmath as mp
import numpy as np

from study import Domain, decode, linear, pack, rne


class IntegerModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.refs = np.fromfile("build/reference.bin", dtype="<u2").reshape(2, 3, 65536)

    def test_signed_ties(self):
        v = np.arange(-20, 21, dtype=np.int64)
        for s in range(1, 5):
            np.testing.assert_array_equal(rne(v, s), np.rint(v / (1 << s)).astype(np.int64))
        np.testing.assert_array_equal(rne(v, -2), v * 4)
        np.testing.assert_array_equal(rne(v, 0), v)

    def test_pack_identity(self):
        for f in (10, 7):
            bias = (1 << (14-f)) - 1
            inf = ((1 << (15-f))-1) << f
            bits = np.arange(1 << f, inf, dtype=np.int64)
            m = (1 << f) + (bits & ((1 << f)-1))
            np.testing.assert_array_equal(pack(m, f, (bits >> f)-bias, f), bits)

    def test_pack_boundaries(self):
        for f in (10, 7):
            bias = (1 << (14-f)) - 1
            inf = ((1 << (15-f))-1) << f
            # min normalのすぐ下の中点は偶数側のmin normalへ。
            self.assertEqual(int(pack((1 << (f+1))-1, f+1, 1-bias, f)), 1 << f)
            self.assertEqual(int(pack((1 << (f+2))-3, f+2, 1-bias, f)), 0)
            self.assertEqual(int(pack((1 << (f+2))-1, f+1, bias, f)), inf)
            self.assertEqual(int(pack((1 << (f+3))-3, f+2, bias, f)), inf-1)

    def test_special_values(self):
        for fi, f in enumerate((10, 7)):
            bias = (1 << (14-f))-1
            inf = ((1 << (15-f))-1) << f
            nan = inf | (1 << (f-1))
            for oi, op in enumerate(("exp", "recip", "rsqrt")):
                ref = self.refs[fi, oi]
                self.assertEqual(int(ref[inf+1]), nan)
                self.assertEqual(int(ref[0]), bias << f if op == "exp" else inf)
                self.assertEqual(int(ref[0x8001]), bias << f if op == "exp" else inf | 0x8000)
                if op == "rsqrt":
                    self.assertEqual(int(ref[(bias << f) | 0x8000]), nan)
                d = Domain(f, op, ref)
                np.testing.assert_array_equal(d.base[~d.active], ref[~d.active])

    def test_linear_exhaustive(self):
        from gen_rtl import PROFILES

        self.assertEqual(set(PROFILES), {"fp16", "bf16"})
        for f, (q, q1), bs in PROFILES.values():
            for oi, op in enumerate(("exp", "recip", "rsqrt")):
                domain = Domain(f, op, self.refs[0 if f == 10 else 1, oi])
                row = domain.metrics(linear(domain, bs[oi], q, q1))
                self.assertEqual(row["violations"], 0, (f, op, row))
                self.assertEqual(row["monotonic"], 0, (f, op, row))

    def test_shared_runtime_datapath(self):
        from gen_rtl import generate

        rtl = generate()
        self.assertIn("input wire is_bf16", rtl)
        self.assertEqual(rtl.count("module FP16BF16ExpRecipRsqrtStudy"), 1)
        self.assertEqual(rtl.count(" * "), 2)
        self.assertIn("wire signed [19:0] product = d * c1;", rtl)
        self.assertIn("wire [25:0] exp_product = mantissa * 15'd23637;", rtl)

    def test_readable_rtl_layout(self):
        from gen_rtl import generate

        lines = generate().splitlines()
        self.assertLessEqual(max(map(len, lines)), 120)
        tables = [line for line in lines if "localparam logic" in line]
        self.assertEqual(len(tables), 12)
        self.assertTrue(all(line.endswith("= '{") for line in tables))

    def test_metrics_reject_bad_classification_and_monotonicity(self):
        domain = Domain(10, "exp", self.refs[0, 0])
        out = domain.ref.copy()
        # normalとInfは隣接bit patternでも許容誤差として扱わない。
        u = int(np.flatnonzero((out > 1024) & (out < domain.inf))[0])
        out[u] = domain.inf
        self.assertGreater(domain.metrics(out)["violations"], 0)
        # 個々の誤差が1 stepでも単調性を独立にrejectする。
        out = domain.ref.copy()
        out[0] += 1
        metrics = domain.metrics(out)
        self.assertEqual(metrics["violations"], 0)
        self.assertGreater(metrics["monotonic"], 0)

    def test_oracle_high_precision_spots(self):
        # binary128と独立な100桁演算で、固定seed抽出と結果分類境界を照合する。
        mp.mp.dps = 100
        rng = np.random.default_rng(20260910)
        for fi, f in enumerate((10, 7)):
            bias = (1 << (14-f))-1
            inf = ((1 << (15-f))-1) << f
            for oi in range(3):
                ref = self.refs[fi, oi]
                category = np.where((ref & 0x7fff) == 0, 0,
                                    np.where((ref & 0x7fff) >= inf, 2, 1))
                borders = np.flatnonzero(np.diff(category))
                cases = np.unique(np.r_[rng.integers(0, 65536, 256), borders, borders+1])
                for u in cases:
                    a = int(u) & 0x7fff
                    if a < (1 << f) or a >= inf or (oi == 2 and u & 0x8000):
                        continue
                    x = mp.mpf(float(decode(u, f)))
                    if oi == 0 and abs(x) >= 1024:
                        continue
                    y = mp.exp(x) if oi == 0 else 1/x if oi == 1 else 1/mp.sqrt(x)
                    sign = 0x8000 if y < 0 else 0
                    y = abs(y)
                    _, e = mp.frexp(y)
                    e = max(int(e)-1, 1-bias)
                    if e > bias:
                        expected = inf
                    else:
                        scaled = mp.ldexp(y, f-e)
                        lo = int(mp.floor(scaled))
                        tail = scaled-lo
                        m = lo + int(tail > mp.mpf('.5') or (tail == mp.mpf('.5') and lo & 1))
                        if m < (1 << f):
                            expected = 0
                        else:
                            if m >= (2 << f):
                                m >>= 1
                                e += 1
                            expected = inf if e > bias else ((e+bias) << f) + m - (1 << f)
                    self.assertEqual(int(ref[u]), expected | sign, (f, oi, hex(int(u))))


if __name__ == "__main__":
    unittest.main()
