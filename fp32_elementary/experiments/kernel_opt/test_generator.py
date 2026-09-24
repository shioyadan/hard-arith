# Copyright 2026 Ryota Shioya and Toru Koizumi
# SPDX-License-Identifier: Apache-2.0
"""生成器の差分範囲と、全係数格子での丸め・幅条件を検査する。"""

import unittest

import numpy as np

from generate import BASE_SHA, VARIANTS, baseline_bytes, candidate, retune, sha, table


class GeneratorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = baseline_bytes()
        assert sha(raw) == BASE_SHA
        cls.baseline = raw.decode()
        cls.c0, cls.changes = retune(cls.baseline)

    def test_retuned_rows(self):
        self.assertEqual(self.changes, [dict(row=55, before=243504808, after=243504810),
                                       dict(row=60, before=257054666, after=257054668)])

    def test_variants(self):
        for name in VARIANTS:
            text = candidate(self.baseline, name, self.c0)
            if name == 'baseline':
                self.assertEqual(text, self.baseline)
            self.assertEqual(text.count('module FP32Elementary #('), 1)
            self.assertEqual(text.count('parameter bit ENABLE_'), 6)
            first = '// BEGIN GENERATED ELEMENTARY TABLES'
            last = '// END GENERATED ELEMENTARY TABLES'
            before = self.baseline.split(first)[1].split(last)[0]
            after = text.split(first)[1].split(last)[0]
            if 'delta18' not in name:
                self.assertEqual(before, after)
            else:
                np.testing.assert_array_equal(table(text, 'exp2_c0_q27'), self.c0)
            for marker in ('    // 数学的に厳密な格子点', '    wire signed [17:0] mantissa_delta_m6_q23'):
                if marker.startswith('    //'):
                    self.assertEqual(text[text.index(marker):], self.baseline[self.baseline.index(marker):])
                else:
                    self.assertEqual(text[text.index(marker):text.index('    // funcごとの係数bank')],
                                     self.baseline[self.baseline.index(marker):self.baseline.index('    // funcごとの係数bank')])

    def test_integer_grid(self):
        banks = [('reciprocal', (25, 17, 8), 32768), ('sqrt_base', (25, 17, 8), 65536),
                 ('sqrt_scaled', (25, 17, 8), 65536), ('rsqrt_base', (25, 17, 8), 32768),
                 ('rsqrt_scaled', (25, 17, 8), 32768), ('log2', (25, 16, 7), 65536),
                 ('exp2', (27, 17, 9), 131072), ('sine', (24, 15, 5), 32768)]
        count = 0
        for name, formats, half in banks:
            coefficients = [table(self.baseline, f'{name}_c{i}_q{q}') << (target-q)
                            for i, (q, target) in enumerate(zip(formats, (27, 18, 9)))]
            delta = np.arange(-half, half+int(name == 'exp2'), dtype=np.int64)
            if name == 'sine':
                delta -= half
            if name != 'exp2':
                delta *= 2
            self.assertGreaterEqual(int(delta.min()), -131072)
            self.assertLessEqual(int(delta.max()), 131072 if name == 'exp2' else 131071)
            for c0, c1, c2 in zip(*coefficients):
                correction = (delta*c2+16384) >> 15
                self.assertTrue(np.all((-16384 <= correction) & (correction < 16384)))
                inner = c1+correction
                accumulator = (c1 << 15)+delta*c2+16384
                self.assertTrue(np.all((-(1 << 35) <= accumulator) & (accumulator < (1 << 35))))
                np.testing.assert_array_equal(inner, accumulator >> 15)
                shift, bias = (15, 16384) if name == 'exp2' else (17, 65536)
                correction = (delta*inner+bias) >> shift
                bits = 22 if name == 'exp2' else 21
                self.assertTrue(np.all((-(1 << (bits-1)) <= correction) & (correction < (1 << (bits-1)))))
                scale = 1 if name == 'exp2' else 4
                self.assertTrue(name == 'exp2' or c0 % 4 == 0)
                accumulator = (c0 << 15)+delta*inner+bias
                self.assertTrue(np.all((-(1 << 43) <= accumulator) & (accumulator < (1 << 43))))
                np.testing.assert_array_equal(c0+correction*scale, (accumulator >> shift)*scale)
                count += len(delta)
        self.assertEqual(count, 71303232)
        print(f'PASS: integer_grid={count}', flush=True)


if __name__ == '__main__':
    unittest.main()
