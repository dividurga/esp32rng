"""
nist_tests.py — All 15 NIST SP 800-22 rev1a tests implemented from scratch.

Verified against the published formulas in nistspecialpublication800-22r1a.pdf.
Each test returns {"score": float, "passed": bool, "eligible": bool}.
score is the p-value (or mean p-value for multi-result tests).
passed = score >= 0.01.  eligible = False means not enough data / prereq failed.
"""

import math
import numpy as np
from scipy.special import gammaincc, erfc as sp_erfc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _erfc(x: float) -> float:
    return float(sp_erfc(x))


def _igamc(a: float, x: float) -> float:
    """Upper regularised incomplete gamma: Γ(a,x)/Γ(a)  (≡ scipy gammaincc)."""
    return float(gammaincc(a, x))


def _result(score: float, eligible: bool = True) -> dict:
    return {"score": score, "passed": eligible and score >= 0.01, "eligible": eligible}


def _na() -> dict:
    return {"score": -1.0, "passed": False, "eligible": False}


# ---------------------------------------------------------------------------
# T01  Frequency (Monobit) Test  §2.1
# ---------------------------------------------------------------------------

def t01_monobit(bits: np.ndarray) -> dict:
    n = len(bits)
    s_n = int(np.sum(bits.astype(np.int64))) * 2 - n   # sum of ±1
    s_obs = abs(s_n) / math.sqrt(n)
    p = _erfc(s_obs / math.sqrt(2))
    return _result(p)


# ---------------------------------------------------------------------------
# T02  Frequency Test within a Block  §2.2
# ---------------------------------------------------------------------------

def t02_block_frequency(bits: np.ndarray, M: int = 128) -> dict:
    n = len(bits)
    N = n // M
    if N < 1:
        return _na()
    blocks = bits[:N * M].reshape(N, M).astype(np.float64)
    pi_i = blocks.mean(axis=1)          # proportion of 1s per block
    chi2 = float(4 * M * np.sum((pi_i - 0.5) ** 2))
    p = _igamc(N / 2.0, chi2 / 2.0)
    return _result(p)


# ---------------------------------------------------------------------------
# T03  Runs Test  §2.3
# ---------------------------------------------------------------------------

def t03_runs(bits: np.ndarray) -> dict:
    n = len(bits)
    pi = float(np.mean(bits))
    tau = 2.0 / math.sqrt(n)
    if abs(pi - 0.5) >= tau:            # frequency prerequisite fails → N/A
        return _na()
    # count transitions: r(k)=1 if bits[k] != bits[k+1]
    transitions = int(np.sum(bits[:-1] != bits[1:]))
    v_n = transitions + 1
    numer = abs(v_n - 2 * n * pi * (1 - pi))
    denom = 2 * math.sqrt(2 * n) * pi * (1 - pi)
    p = _erfc(numer / denom)
    return _result(p)


# ---------------------------------------------------------------------------
# T04  Longest Run of Ones in a Block  §2.4
# ---------------------------------------------------------------------------

# Hardcoded NIST table values (PDF §2.4 / §3.4)
_LR_PARAMS = {
    # (min_n, M, K, N, boundaries, pi)
    128:    (8,   3, 16,
             [1, 2, 3, 4],           # <=v0, v1, v2, >=v3
             [0.21484375, 0.36328125, 0.23046875, 0.1875]),
    6272:   (128, 5, 49,
             [4, 5, 6, 7, 8, 9],     # <=v0, v1..v4, >=v5
             [0.1174035788, 0.242955959, 0.249363483,
              0.17517706,   0.102701071, 0.112398847]),
    750000: (10000, 6, 75,
             [10, 11, 12, 13, 14, 15, 16],  # <=v0, v1..v5, >=v6
             [0.0882, 0.2092, 0.2483, 0.1933, 0.1208, 0.0675, 0.0727]),
}


def _longest_run_of_ones(block: np.ndarray) -> int:
    """Return longest run of 1s in a binary block using numpy."""
    # pad with 0s on both sides, find transitions, measure runs
    b = block.astype(np.int8)
    padded = np.concatenate(([0], b, [0]))
    edges = np.diff(padded)
    starts = np.where(edges == 1)[0]
    ends   = np.where(edges == -1)[0]
    if len(starts) == 0:
        return 0
    return int(np.max(ends - starts))


def t04_longest_run(bits: np.ndarray) -> dict:
    n = len(bits)
    entry = None
    for min_n in sorted(_LR_PARAMS.keys(), reverse=True):
        if n >= min_n:
            entry = _LR_PARAMS[min_n]
            break
    if entry is None:
        return _na()
    M, K, N, bounds, pi = entry
    pi = np.array(pi, dtype=np.float64)

    nu = np.zeros(K + 1, dtype=np.float64)
    for i in range(N):
        run = _longest_run_of_ones(bits[i * M:(i + 1) * M])
        if run <= bounds[0]:
            nu[0] += 1
        elif run >= bounds[-1]:
            nu[K] += 1
        else:
            for j in range(1, K):
                if run == bounds[j]:
                    nu[j] += 1
                    break

    expected = N * pi
    chi2 = float(np.sum((nu - expected) ** 2 / expected))
    p = _igamc(K / 2.0, chi2 / 2.0)
    return _result(p)


# ---------------------------------------------------------------------------
# T05  Binary Matrix Rank Test  §2.5
# ---------------------------------------------------------------------------

def _gf2_rank(m: np.ndarray) -> int:
    """Binary matrix rank over GF(2) via row reduction."""
    mat = m.copy()
    rows, cols = mat.shape
    rank = 0
    for col in range(cols):
        pivot = -1
        for row in range(rank, rows):
            if mat[row, col]:
                pivot = row
                break
        if pivot == -1:
            continue
        mat[[rank, pivot]] = mat[[pivot, rank]]
        for row in range(rows):
            if row != rank and mat[row, col]:
                mat[row] ^= mat[rank]
        rank += 1
    return rank


def t05_matrix_rank(bits: np.ndarray, M: int = 32, Q: int = 32) -> dict:
    n = len(bits)
    N = n // (M * Q)
    if N < 38:          # NIST minimum: at least 38 matrices
        return _na()
    fm = fm1 = 0
    for i in range(N):
        block = bits[i * M * Q:(i + 1) * M * Q].reshape(M, Q)
        r = _gf2_rank(block)
        if r == M:
            fm += 1
        elif r == M - 1:
            fm1 += 1
    frest = N - fm - fm1
    chi2 = ((fm  - 0.2888 * N) ** 2 / (0.2888 * N) +
            (fm1 - 0.5776 * N) ** 2 / (0.5776 * N) +
            (frest - 0.1336 * N) ** 2 / (0.1336 * N))
    p = math.exp(-chi2 / 2.0)
    return _result(p)


# ---------------------------------------------------------------------------
# T06  Discrete Fourier Transform (Spectral) Test  §2.6
# ---------------------------------------------------------------------------

def t06_dft(bits: np.ndarray) -> dict:
    n = len(bits)
    x = bits.astype(np.float64) * 2 - 1        # {0,1} → {-1,+1}
    s = np.abs(np.fft.rfft(x))                  # magnitudes; length n//2+1
    # use first n//2 components (S' in the spec)
    s = s[:n // 2]
    T = math.sqrt(math.log(1.0 / 0.05) * n)    # 95 % threshold (log = natural)
    n0 = 0.95 * n / 2.0                         # expected peaks below T
    n1 = float(np.sum(s < T))                   # observed peaks below T
    d = (n1 - n0) / math.sqrt(n * 0.95 * 0.05 / 4.0)
    p = _erfc(abs(d) / math.sqrt(2))
    return _result(p)


# ---------------------------------------------------------------------------
# T07  Non-Overlapping Template Matching Test  §2.7
# ---------------------------------------------------------------------------


def t07_non_overlapping_template(bits: np.ndarray, m: int = 9, N: int = 8) -> dict:
    """Non-overlapping template matching (§2.7).

    Uses the aperiodic template 000…001 (m-1 zeros then one 1), which is the
    example given in §2.7.8 and is always aperiodic.  The mu/sigma² formulae
    in §2.7 require an aperiodic template; periodic templates (e.g. all-ones)
    violate the independence assumptions and produce invalid chi-squared values.
    """
    n = len(bits)
    M = n // N
    if M < 10:
        return _na()

    mu = (M - m + 1) / 2.0 ** m
    sigma2 = M * (1.0 / 2 ** m - (2 * m - 1) / 4.0 ** m)
    tid = 1          # 000...001 as integer
    powers = 1 << np.arange(m - 1, -1, -1, dtype=np.int64)

    W = np.empty(N, dtype=np.float64)
    for j in range(N):
        block = bits[j * M:(j + 1) * M].astype(np.int64)
        wins = np.lib.stride_tricks.sliding_window_view(block, m)
        ids = (wins @ powers).astype(np.int64)
        match_pos = np.where(ids == tid)[0]
        count = 0
        last_end = -1
        for pos in match_pos:
            if pos >= last_end:
                count += 1
                last_end = int(pos) + m
        W[j] = count

    chi2 = float(np.sum((W - mu) ** 2 / sigma2))
    p = _igamc(N / 2.0, chi2 / 2.0)
    return _result(p)


# ---------------------------------------------------------------------------
# T08  Overlapping Template Matching Test  §2.8
# ---------------------------------------------------------------------------

# NIST tabulated π for m=9, M=1032, K=5  (§2.8.4)
_OTM_PI = np.array([0.364091, 0.185659, 0.139381,
                    0.100571, 0.070432, 0.139865])


def t08_overlapping_template(bits: np.ndarray, m: int = 9,
                              M: int = 1032, K: int = 5) -> dict:
    n = len(bits)
    N = n // M
    if N < 100:
        return _na()
    template = np.ones(m, dtype=np.int8)
    counts = np.empty(N, dtype=np.int32)
    for i in range(N):
        blk = bits[i * M:(i + 1) * M]
        wins = np.lib.stride_tricks.sliding_window_view(blk, m)
        c = int(np.sum(np.all(wins == template, axis=1)))
        counts[i] = min(c, K)
    nu = np.array([np.sum(counts == v) for v in range(K)]
                  + [np.sum(counts >= K)], dtype=np.float64)
    expected = N * _OTM_PI
    chi2 = float(np.sum((nu - expected) ** 2 / expected))
    p = _igamc(K / 2.0, chi2 / 2.0)
    return _result(p)


# ---------------------------------------------------------------------------
# T09  Maurer's "Universal Statistical" Test  §2.9
# ---------------------------------------------------------------------------

# Lookup table from §2.9 (and Handbook of Applied Cryptography)
_MAURER_EV = {
    6:  (5.2177052, 2.954),
    7:  (6.1962507, 3.125),
    8:  (7.1836656, 3.238),
    9:  (8.1764248, 3.311),
    10: (9.1723243, 3.356),
    11: (10.170032, 3.384),
    12: (11.168765, 3.401),
    13: (12.168070, 3.410),
    14: (13.167693, 3.416),
    15: (14.167488, 3.419),
    16: (15.167379, 3.421),
}

_MAURER_MIN_N = {
    6:  387840, 7:  904960, 8:  2068480, 9:  4654080,
    10: 10342400, 11: 22753280, 12: 49643520, 13: 107560960,
    14: 231669760, 15: 496435200, 16: 1059061760,
}


def t09_maurers_universal(bits: np.ndarray) -> dict:
    n = len(bits)
    # Choose L
    L = None
    for l in range(16, 5, -1):
        if n >= _MAURER_MIN_N.get(l, 10 ** 18):
            L = l
            break
    if L is None:
        return _na()

    Q = 10 * (2 ** L)           # initialization blocks
    K = n // L - Q              # test blocks
    if K <= 0:
        return _na()

    ev, variance = _MAURER_EV[L]
    table = np.zeros(2 ** L, dtype=np.int64)

    # Vectorize block→integer index for all (init + test) blocks at once
    total_blocks = (Q + K)
    powers = (1 << np.arange(L - 1, -1, -1, dtype=np.int64))
    all_ids = (bits[:total_blocks * L]
               .reshape(total_blocks, L)
               .astype(np.int64) @ powers)   # shape (Q+K,), values 0..2^L-1

    # Fill initialization table (block numbers are 1-indexed per spec)
    for i in range(1, Q + 1):
        table[all_ids[i - 1]] = i

    # Accumulate log2 sum over test blocks.
    # table[idx] == 0 means pattern not seen in init; distance = i - 0 = i (correct per spec).
    total = 0.0
    for i in range(Q + 1, Q + K + 1):
        idx = all_ids[i - 1]
        total += math.log2(i - table[idx])   # i - table[idx] >= 1 always
        table[idx] = i

    fn = total / K
    c = (0.7 - 0.8 / L
         + (4.0 + 32.0 / L) * (K ** (-3.0 / L)) / 15.0)
    sigma = c * math.sqrt(variance / K)
    p = _erfc(abs(fn - ev) / (math.sqrt(2) * sigma))
    return _result(p)


# ---------------------------------------------------------------------------
# T10  Linear Complexity Test  §2.10
# ---------------------------------------------------------------------------

def _berlekamp_massey(seq) -> int:
    n = len(seq)
    C = [1]; B = [1]
    L = 0; x = 1
    for N in range(n):
        d = int(seq[N])
        for i in range(1, L + 1):
            d ^= int(C[i]) * int(seq[N - i])
        d &= 1
        if d == 0:
            x += 1
        elif 2 * L <= N:
            T = C[:]
            Bx = [0] * x + B
            sz = max(len(C), len(Bx))
            C  = (C  + [0] * sz)[:sz]
            Bx = (Bx + [0] * sz)[:sz]
            C  = [(C[i] ^ Bx[i]) & 1 for i in range(sz)]
            L  = N + 1 - L; B = T; x = 1
        else:
            Bx = [0] * x + B
            sz = max(len(C), len(Bx))
            C  = (C  + [0] * sz)[:sz]
            Bx = (Bx + [0] * sz)[:sz]
            C  = [(C[i] ^ Bx[i]) & 1 for i in range(sz)]
            x += 1
    return L


# NIST §2.10 pi values (M=500, K=6 categories)
_LC_PI = np.array([0.010417, 0.031250, 0.125000, 0.500000,
                   0.250000, 0.062500, 0.020833])


def t10_linear_complexity(bits: np.ndarray, M: int = 500) -> dict:
    n = len(bits)
    K_blocks = n // M
    if K_blocks < 200:
        return _na()

    mu = (M / 2.0 + (9.0 + (-1) ** (M + 1)) / 36.0
          - (M / 3.0 + 2.0 / 9.0) / 2.0 ** M)

    nu = np.zeros(7, dtype=np.float64)
    for i in range(K_blocks):
        block = bits[i * M:(i + 1) * M].tolist()
        L = _berlekamp_massey(block)
        T = (-1) ** M * (L - mu) + 2.0 / 9.0
        if   T <= -2.5: nu[0] += 1
        elif T <= -1.5: nu[1] += 1
        elif T <= -0.5: nu[2] += 1
        elif T <=  0.5: nu[3] += 1      # fixed: 0.5 not 0.0
        elif T <=  1.5: nu[4] += 1
        elif T <=  2.5: nu[5] += 1
        else:           nu[6] += 1

    expected = K_blocks * _LC_PI
    chi2 = float(np.sum((nu - expected) ** 2 / expected))
    p = _igamc(3.0, chi2 / 2.0)        # K=6 df → igamc(K/2, chi2/2)
    return _result(p)


# ---------------------------------------------------------------------------
# T11  Serial Test  §2.11
# ---------------------------------------------------------------------------

def _psi2(bits_aug: np.ndarray, m: int, n: int) -> float:
    """psi^2_m from §2.11 using pattern counts."""
    if m == 0:
        return 0.0
    wins = np.lib.stride_tricks.sliding_window_view(bits_aug[:n + m - 1], m)
    powers = 1 << np.arange(m - 1, -1, -1, dtype=np.int64)
    ids = (wins.astype(np.int64) @ powers)
    counts = np.bincount(ids, minlength=2 ** m).astype(np.float64)
    return float(2 ** m / n * np.sum(counts ** 2) - n)


def t11_serial(bits: np.ndarray, m: int = 16) -> dict:
    n = len(bits)
    if m >= math.floor(math.log2(n)) - 1:
        return _na()
    # Augmented sequence (circular): append first m-1 bits
    bits_aug = np.concatenate([bits, bits[:m - 1]])
    psi_m   = _psi2(bits_aug, m,     n)
    psi_m1  = _psi2(bits_aug, m - 1, n)
    psi_m2  = _psi2(bits_aug, m - 2, n)
    del1 = psi_m - psi_m1
    del2 = psi_m - 2 * psi_m1 + psi_m2
    p1 = _igamc(2 ** (m - 2), del1 / 2.0)
    p2 = _igamc(2 ** (m - 3), del2 / 2.0)
    score = min(p1, p2)
    return _result(score)


# ---------------------------------------------------------------------------
# T12  Approximate Entropy Test  §2.12
# ---------------------------------------------------------------------------

def _phi(bits_aug: np.ndarray, m: int, n: int) -> float:
    """phi^(m) = sum(C_i * log C_i) from §2.12."""
    wins = np.lib.stride_tricks.sliding_window_view(bits_aug[:n + m - 1], m)
    powers = 1 << np.arange(m - 1, -1, -1, dtype=np.int64)
    ids = (wins.astype(np.int64) @ powers)
    counts = np.bincount(ids, minlength=2 ** m).astype(np.float64)
    probs = counts / n
    with np.errstate(divide='ignore'):
        log_p = np.where(probs > 0, np.log(probs), 0.0)
    return float(np.sum(probs * log_p))


def t12_approximate_entropy(bits: np.ndarray, m: int = 10) -> dict:
    n = len(bits)
    if m >= math.floor(math.log2(n)) - 5:
        return _na()
    bits_aug = np.concatenate([bits, bits[:m]])    # append m bits (for m+1 windows)
    phi_m   = _phi(bits_aug, m,     n)
    phi_m1  = _phi(bits_aug, m + 1, n)
    apen = phi_m - phi_m1
    chi2 = 2 * n * (math.log(2) - apen)
    p = _igamc(2 ** (m - 1), chi2 / 2.0)
    return _result(p)


# ---------------------------------------------------------------------------
# T13  Cumulative Sums (Cusums) Test  §2.13
# ---------------------------------------------------------------------------

def _cusums_p(n: int, z: int) -> float:
    from math import erfc as _erfc_math, sqrt
    sum_a = 0.0
    lo = int(math.floor((-n / z + 1) / 4))
    hi = int(math.floor(( n / z - 1) / 4))
    for k in range(lo, hi + 1):
        sum_a += (0.5 * _erfc_math(-((4*k + 1)*z) / sqrt(n) * sqrt(0.5))
                - 0.5 * _erfc_math(-((4*k - 1)*z) / sqrt(n) * sqrt(0.5)))
    sum_b = 0.0
    lo2 = int(math.floor((-n / z - 3) / 4))
    for k in range(lo2, hi + 1):
        sum_b += (0.5 * _erfc_math(-((4*k + 3)*z) / sqrt(n) * sqrt(0.5))
                - 0.5 * _erfc_math(-((4*k + 1)*z) / sqrt(n) * sqrt(0.5)))
    return 1.0 - sum_a + sum_b


def t13_cumulative_sums(bits: np.ndarray) -> dict:
    walk = bits.astype(np.int64) * 2 - 1
    n = len(walk)
    fwd = np.cumsum(walk)
    bwd = np.cumsum(walk[::-1])
    z_f = int(np.max(np.abs(fwd)))
    z_b = int(np.max(np.abs(bwd)))
    p_f = _cusums_p(n, z_f)
    p_b = _cusums_p(n, z_b)
    score = min(p_f, p_b)
    return _result(score)


# ---------------------------------------------------------------------------
# T14  Random Excursions Test  §2.14
# ---------------------------------------------------------------------------

def _re_pi(x: int, k: int) -> float:
    """Probability that state x occurs exactly k times in a cycle (§3.14)."""
    ax = abs(x)
    p0 = 1.0 - 1.0 / (2 * ax)
    if k == 0:
        return p0
    base = 1.0 / (4.0 * ax * ax)
    tail = (1.0 - 1.0 / (2 * ax)) ** (k - 1)
    return base * tail


def t14_random_excursions(bits: np.ndarray) -> dict:
    walk = bits.astype(np.int64) * 2 - 1
    s = np.concatenate(([0], np.cumsum(walk), [0]))
    zero_pos = np.where(s == 0)[0]
    J = len(zero_pos) - 1       # number of cycles
    if J < 500:
        return _na()

    states = [-4, -3, -2, -1, 1, 2, 3, 4]
    p_values = []

    for x in states:
        # Count per-cycle occurrences of state x
        v = np.zeros(6, dtype=np.float64)
        for c in range(J):
            cycle = s[zero_pos[c]:zero_pos[c + 1] + 1]
            occ = int(np.sum(cycle == x))
            if occ >= 5:
                v[5] += 1
            else:
                v[occ] += 1

        # Theoretical probabilities
        pi_k = np.array([_re_pi(x, k) for k in range(5)], dtype=np.float64)
        pi_k5 = 1.0 - pi_k.sum()
        pi_all = np.append(pi_k, pi_k5)

        expected = J * pi_all
        chi2 = float(np.sum((v - expected) ** 2 / expected))
        p_values.append(_igamc(2.5, chi2 / 2.0))

    score = float(np.min(p_values))
    passed = all(p >= 0.01 for p in p_values)
    return {"score": score, "passed": passed, "eligible": True}


# ---------------------------------------------------------------------------
# T15  Random Excursions Variant Test  §2.15
# ---------------------------------------------------------------------------

def t15_random_excursions_variant(bits: np.ndarray) -> dict:
    walk = bits.astype(np.int64) * 2 - 1
    s = np.concatenate(([0], np.cumsum(walk), [0]))
    J = int(np.count_nonzero(s[1:] == 0))
    if J < 500:
        return _na()

    states = list(range(-9, 0)) + list(range(1, 10))
    p_values = []
    for x in states:
        xi = int(np.sum(s == x))
        denom = math.sqrt(2.0 * J * (4.0 * abs(x) - 2.0))
        p = _erfc(abs(xi - J) / denom)
        p_values.append(p)

    score = float(np.mean(p_values))
    passed = all(p >= 0.01 for p in p_values)
    return {"score": score, "passed": passed, "eligible": True}


# ---------------------------------------------------------------------------
# Battery runner — returns dict keyed by the same names as nistrng uses
# ---------------------------------------------------------------------------

BATTERY_KEYS = [
    "monobit",
    "frequency_within_block",
    "runs",
    "longest_run_ones_in_a_block",
    "binary_matrix_rank",
    "dft",
    "non_overlapping_template_matching",
    "overlapping_template_matching",
    "maurers_universal",
    "linear_complexity",
    "serial",
    "approximate_entropy",
    "cumulative sums",
    "random_excursion",
    "random_excursion_variant",
]

_DISPATCH = {
    "monobit":                         t01_monobit,
    "frequency_within_block":          t02_block_frequency,
    "runs":                            t03_runs,
    "longest_run_ones_in_a_block":     t04_longest_run,
    "binary_matrix_rank":              t05_matrix_rank,
    "dft":                             t06_dft,
    "non_overlapping_template_matching": t07_non_overlapping_template,
    "overlapping_template_matching":   t08_overlapping_template,
    "maurers_universal":               t09_maurers_universal,
    "linear_complexity":               t10_linear_complexity,
    "serial":                          t11_serial,
    "approximate_entropy":             t12_approximate_entropy,
    "cumulative sums":                 t13_cumulative_sums,
    "random_excursion":                t14_random_excursions,
    "random_excursion_variant":        t15_random_excursions_variant,
}


def run_all(bits: np.ndarray, verbose: bool = True) -> dict:
    """Run all 15 tests.  Returns dict matching nistrng key names."""
    import time
    results = {}
    n = len(BATTERY_KEYS)
    for i, name in enumerate(BATTERY_KEYS, 1):
        if verbose:
            print(f"      [{i:2d}/{n}] {name} …", end="", flush=True)
        t0 = time.time()
        r = _DISPATCH[name](bits)
        elapsed = time.time() - t0
        if verbose:
            if not r["eligible"]:
                label = "N/A"
            elif r["passed"]:
                label = "PASS"
            else:
                label = "FAIL"
            print(f" {label}  (p={r['score']:.2e}, {elapsed:.1f}s)")
        results[name] = r
    return results
