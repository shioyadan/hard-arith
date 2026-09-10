# Copyright 2026 Ryota Shioya and Toru Koizumi
# SPDX-License-Identifier: Apache-2.0
"""16 bit三機能の、範囲縮小と中間丸めを含めた一次方式の整数モデル。"""
import hashlib

import numpy as np

OPS = ("exp", "recip", "rsqrt")


def rne(v, shift):
    """signed値にも対応する偶数丸め。左shiftも同じ入口で扱う。"""
    v = np.asarray(v, dtype=np.int64)
    shift = np.asarray(shift, dtype=np.int64)
    s = np.clip(shift, 1, 60)
    low = v & ((np.int64(1) << s) - 1)
    half = np.int64(1) << (s - 1)
    high = v >> s
    rounded = high + ((low > half) | ((low == half) & ((high & 1) != 0)))
    return np.where(shift > 0, rounded, v << np.clip(-shift, 0, 60))


def width(v, signed=False):
    v = np.asarray(v, dtype=np.int64)
    lo, hi = int(v.min()), int(v.max())
    if signed:
        return max(1, hi.bit_length() + 1, (~lo).bit_length() + 1 if lo < 0 else 1)
    assert lo >= 0
    return max(1, hi.bit_length())


def pack(y, q, scale, f):
    """正の整数 y * 2^(scale-q) を対象形式にRNEし、最後にFTZ。"""
    y = np.asarray(y, dtype=np.int64)
    bias = (1 << (14 - f)) - 1
    inf = ((1 << (15 - f)) - 1) << f
    # 今回のyは53 bit未満。frexpへの変換は整数として厳密。
    assert np.all((y >= 0) & (y < (1 << 53)))
    exponent = np.frexp(y.astype(np.float64))[1].astype(np.int64) - 1 + scale - q
    exponent = np.maximum(exponent, 1 - bias)
    m = rne(y, q + exponent - f - scale)
    carry = m >= (2 << f)
    m = np.where(carry, m >> 1, m)
    exponent = exponent + carry
    bits = ((exponent + bias) << f) + m - (1 << f)
    return np.where((m < (1 << f)) | (y == 0), 0,
                    np.where(exponent > bias, inf, bits)).astype(np.int64)


def decode(u, f):
    u = np.asarray(u, dtype=np.int64)
    bias = (1 << (14 - f)) - 1
    e, m = (u & 0x7fff) >> f, (u & ((1 << f) - 1)) + (1 << f)
    x = np.ldexp(m.astype(float), e - bias - f)
    return np.where(e == 0, 0.0, x) * np.where(u & 0x8000, -1, 1)


class Domain:
    def __init__(self, f, op, ref):
        self.f, self.op, self.ref = f, op, ref.astype(np.int64)
        self.bias = (1 << (14 - f)) - 1
        self.inf = ((1 << (15 - f)) - 1) << f
        self.nan = self.inf | (1 << (f - 1))
        u = np.arange(65536, dtype=np.int64)
        self.u = u
        a, sign = u & 0x7fff, u & 0x8000
        exponent = a >> f
        self.frac = u & ((1 << f) - 1)
        self.e = exponent - self.bias
        self.x = decode(u, f)
        normal = (exponent != 0) & (a < self.inf)
        self.active = normal & ((sign == 0) if op == "rsqrt" else True)
        if op == "exp":
            self.active &= (self.x > -128) & (self.x < 128)
            self.base = np.where(sign != 0, 0, self.inf)
            self.base = np.where(exponent == 0, self.bias << f, self.base)
        elif op == "recip":
            self.base = np.where(exponent == 0, sign | self.inf, sign)
        else:
            self.base = np.where(exponent == 0, sign | self.inf,
                                 np.where(sign != 0, self.nan, 0))
        self.base = np.where(a > self.inf, self.nan, self.base)
        # 数値順の入力列を準備し、poleをまたがない領域で単調性を確認する。
        groups = [np.r_[np.arange(self.inf | 0x8000, 0x7fff, -1),
                        np.arange(self.inf + 1)]] if op == "exp" else (
            [np.arange(self.inf | 0x8000, 0x7fff, -1), np.arange(self.inf + 1)]
            if op == "recip" else [np.arange(self.inf + 1)])
        self.groups = groups

    def finish(self, y, q):
        a = self.active
        out = self.base.copy()
        if self.op == "exp":
            values, scale = y
            out[a] = pack(values, q, scale, self.f)
        else:
            idx = self.frac[a]
            scale = -self.e[a]
            if self.op == "rsqrt":
                idx = idx + (self.e[a] & 1) * (1 << self.f)
                scale = -(self.e[a] >> 1)
            out[a] = pack(y[idx], q, scale, self.f)
            if self.op == "recip":
                out[a] |= self.u[a] & 0x8000
        return out

    def metrics(self, out):
        a, b = self.ref & 0x7fff, out & 0x7fff
        rn = (a >= (1 << self.f)) & (a < self.inf)
        on = (b >= (1 << self.f)) & (b < self.inf)
        valid = rn & on & ((out & 0x8000) == (self.ref & 0x8000))
        errors = np.abs(out - self.ref)
        bad = np.where(valid, errors > 1, out != self.ref)
        inversions = 0
        for g in self.groups:
            v = out[g]
            key = np.where(v & 0x8000, 0xffff - v, v | 0x8000)
            delta = np.diff(key)
            inversions += int(np.count_nonzero(delta < 0 if self.op == "exp" else delta > 0))
        return {"tested": 65536, "max_step": int(errors[valid].max(initial=0)),
                "violations": int(np.count_nonzero(bad)), "monotonic": inversions,
                "exact": int(np.count_nonzero(out == self.ref)),
                "output_sha256": hashlib.sha256(out.astype("<u2").tobytes()).hexdigest()}


def coefficients(op, b):
    n = 1 << b
    c = (np.arange(n) + 0.5) / n + (0 if op == "exp" else 1)
    # 二つのChebyshev節点で一次補間し、係数は後段で量子化する。
    d = np.cos(np.pi * (np.arange(2) + .5) / 2) / (2 * n)
    rows = []
    for parity in range(2 if op == "rsqrt" else 1):
        x = c[:, None] + d
        y = 2**x if op == "exp" else 1/x if op == "recip" else 1/np.sqrt(x * (1 << parity))
        rows.append(np.polynomial.polynomial.polyfit(d, y.T, 1).T)
    return np.concatenate(rows)


def residual(domain, b, q):
    f, op = domain.f, domain.op
    if op == "exp":
        # 仮数にQ14のlog2(e)を掛け、指数依存shiftの後に一度だけRNEする。
        m = (1 << f) + domain.frac[domain.active]
        z = rne(m * 23637, f + 14 - q - domain.e[domain.active])
        z *= np.where(domain.x[domain.active] < 0, -1, 1)
        scale, t = z >> q, z & ((1 << q) - 1)
        index = t >> (q - b)
        d = t - ((2 * index + 1) << (q - b - 1))
        return d, index, scale
    m = np.tile(np.arange(1 << f, dtype=np.int64), 2 if op == "rsqrt" else 1)
    index = m >> (f - b)
    d = (m << (q - f)) - ((2 * index + 1) << (q - b - 1))
    if op == "rsqrt":
        index[(1 << f):] += (1 << b)
    return d, index, None


def linear(domain, b, q, q1):
    c = coefficients(domain.op, b)
    c0 = np.rint(c[:, 0] * (1 << q)).astype(np.int64)
    c1 = np.rint(c[:, 1] * (1 << q1)).astype(np.int64)
    d, idx, scale = residual(domain, b, q)
    value = c0[idx] + rne(d * c1[idx], q1)
    if domain.op != "exp":
        value[0] = 1 << q  # recip(1)／rsqrt(1)を正確にする。
    return domain.finish((value, scale) if domain.op == "exp" else value, q)
