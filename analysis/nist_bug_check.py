"""Run suspected-buggy nistrng tests on purely random 8M bits.
If they FAIL on random data → nistrng bug.  If they PASS → real failure in your data.
"""
import numpy as np
from nistrng import run_all_battery, SP800_22R1A_BATTERY

rng  = np.random.default_rng(42)
bits = rng.integers(0, 2, size=7_998_720, dtype=np.int8)
print(f"Testing {len(bits):,} purely random bits (numpy seed 42)\n")

suspect = [
    "dft",
    "maurers_universal",
    "linear_complexity",
    "serial",
    "approximate_entropy",
    "overlapping_template_matching",
]

for name in suspect:
    res = run_all_battery(bits, {name: SP800_22R1A_BATTERY[name]})
    if res:
        r, _ = res[0]
        verdict = "PASS" if r.passed else "FAIL  ← likely nistrng bug"
        print(f"  {name:<40} {verdict}  p={r.score:.2e}")
    else:
        print(f"  {name:<40} N/A")
