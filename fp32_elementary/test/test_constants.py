# Copyright 2026 Ryota Shioya and Toru Koizumi
# SPDX-License-Identifier: Apache-2.0
"""係数探索の境界選択と、極値での丸め逆行の回帰検査。"""

import math
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from gen_constants import choose_monotonic_path, round_signed_shift_array, tune_row


class MonotonicConstantsTest(unittest.TestCase):
    def test_increasing_boundary_requires_nonminimal_row(self):
        domains = [[(10, 1.0, 2.0, 0), (11, 1.0, 1.5, 1)],
                   [(20, 1.75, 3.0, 0)]]
        self.assertEqual([row[0] for row in choose_monotonic_path(domains, 1, 3.0)],
                         [11, 20])

    def test_decreasing_boundary(self):
        domains = [[(10, 3.0, 1.0, 0), (11, 3.0, 2.0, 1)],
                   [(20, 1.5, 0.5, 0)]]
        self.assertEqual([row[0] for row in choose_monotonic_path(domains, -1, 0.5)],
                         [11, 20])

    def test_endpoint_excludes_overshoot(self):
        domains = [[(10, 0.5, 1.1, 0), (11, 0.5, 1.0, 1)]]
        self.assertEqual(choose_monotonic_path(domains, 1, 1.0)[0][0], 11)

    def test_impossible_paths_fail(self):
        for domains, direction, endpoint in [
            ([], 1, 1.0), ([[]], 1, 1.0),
            ([[(1, 0.0, 1.0, 0)]], 0, 1.0),
            ([[(1, 0.0, 1.0, 0)], [(2, 0.5, 2.0, 0)]], 1, 2.0),
            ([[(1, 0.0, 2.0, 0)]], 1, 1.0),
            ([[(1, 2.0, 0.0, 0)]], -1, 1.0),
        ]:
            with self.subTest(domains=domains, direction=direction):
                with self.assertRaises(ValueError):
                    choose_monotonic_path(domains, direction, endpoint)

    def test_signed_rounding_ties_toward_positive(self):
        result = round_signed_shift_array(np.array([-7, -6, -5, 5, 6, 7]), 2)
        np.testing.assert_array_equal(result, [-2, -1, -1, 1, 2, 2])

    def test_sine_extremum_preserves_prefix_and_monotonicity(self):
        c0, c1, c2, _ = tune_row(
            lambda x: math.sin(math.pi*x), 0.5, 1/256, 24, 15, 5,
            right_endpoint=True, direction=1,
        )
        self.assertTrue(0 <= c0 < (1 << 24))
        self.assertGreaterEqual(c1, 0)
        self.assertLessEqual(c2, 0)
        delta = np.arange(-(1 << 16), 0, dtype=np.int64)
        inner = (c1 << 3)+round_signed_shift_array(delta*c2, 10)
        value = (c0 << 1)+round_signed_shift_array(delta*inner, 16)
        output = (value*2.0**-25).astype(np.float32)
        self.assertTrue(np.all(np.diff(output.astype(np.float64)) >= 0))
        self.assertLessEqual(output[-1], 1.0)
        arguments = 0.5+delta*2.0**-23
        for edge in (-2.0**-24, 2.0**-24):
            reference = np.sin(np.pi*np.clip(arguments+edge, 0.0, 0.5))
            error = np.max(np.abs(output.astype(np.float64)-reference))
            self.assertLess(error, 4*2.0**-23)


if __name__ == "__main__":
    unittest.main()
