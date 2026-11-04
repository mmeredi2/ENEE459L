
from __future__ import annotations

from typing import Any, Iterable, Sequence

from schema import LATENCY_PERCENTILES, REL_FLOOR

import json
from pathlib import Path

########################################################
##########   Helper functions         ##################
########################################################


def deviation_sentence(abs_res: dict[str, Any], rel_res: dict[str, Any]) -> str:
    """The two deviation metrics in one line, with the caveat. Provided complete.

    Read it before writing `max_rel_dev`. The clause after the semicolon is the
    honest disclosure and it appears whenever any denominator was floored --
    which, on a classification head, is almost always.
    """
    line = (f"max |a-b| = {abs_res['max_abs']:.6g} at index {abs_res['index']}; "
            f"max relative = {rel_res['max_rel']:.6g}")
    if rel_res["floored"]:
        line += (f" (denominator floored on {rel_res['floored']} of "
                 f"{rel_res['n']} entries; smallest |b| was "
                 f"{rel_res['denom_min']:.3g})")
    return line


def decision_sentence(dm: dict[str, Any], tol: float) -> str:
    """The claim `decision_margin` licenses, or the one it refuses. Provided."""
    if dm["safe"]:
        return (f"no decision flips: the smallest margin over {dm['n']} inputs "
                f"is {dm['min']:.6g} and the deviation is {tol:.6g}")
    return (f"{dm['below_tol']} of {dm['n']} decisions sit inside the "
            f"deviation: smallest margin {dm['min']:.6g} at row {dm['argmin']} "
            f"against a deviation of {tol:.6g}")


class AgreementError(ValueError):
    """A comparison this module cannot make. `engine.py` exits 3."""


def _finite(v: Any, where: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise AgreementError(f"{where} is {v!r}, which is not a number.")
    f = float(v)
    if f != f or f in (float("inf"), float("-inf")):
        raise AgreementError(
            f"{where} is {f}. A NaN or an infinity in an output array is the "
            "run failing quietly; it is not a value to take a maximum over."
        )
    return f


def _percentile(xs: Sequence[float], q: float) -> float:
    """Linear interpolation between the two nearest ranks. Provided complete.

    The same implementation Labs 04 through 08 use, here for the same reason:
    a lab whose percentile is nearest-rank and a lab whose percentile
    interpolates produce different p95s from the same samples, and a student
    comparing this week's table against last week's should be comparing the
    board and not the arithmetic.
    """
    s = sorted(float(x) for x in xs)
    if not s:
        raise AgreementError("no samples.")
    if len(s) == 1:
        return s[0]
    pos = (len(s) - 1) * (float(q) / 100.0)
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    frac = pos - lo
    return s[lo] + (s[hi] - s[lo]) * frac


########################################################
##########    Start from here          #################
########################################################


def latency_report(ms: Iterable[float]) -> dict[str, Any]:
    report: dict[str, Any] = {}
    samples: list[float] = []
    for i in ms:
        result = _finite(i, "latency sample")
        if result < 0:
            raise AgreementError(f"latency sample {result} is negative.")
        samples.append(result)

    n = len(samples)
    if n == 0:
        raise AgreementError("no latency samples.")

    mean = 1/n * sum(samples)
    worst = max(samples)

    for q in LATENCY_PERCENTILES:
        p = _percentile(samples, q)
        report[f"p{q}"] = p

    jitter = report["p95"] - report["p50"]

    return {
        "n": n,
        "mean": mean,
        "worst": worst,
        "jitter": jitter,
        "p50": report["p50"],
        "p95": report["p95"],
        "p99": report["p99"]
    }



def speedup(base_ms: float, other_ms: float) -> dict[str, Any]:
    b_finite = _finite(base_ms, "base_ms")
    o_finite = _finite(other_ms, "other_ms")

    if b_finite <= 0:
        raise AgreementError(f"base_ms {base_ms} is not positive.")
    if o_finite <= 0:
        raise AgreementError(f"other_ms {other_ms} is not positive.")

    saved_ms = b_finite - o_finite
    factor = b_finite / o_finite

    faster = False
    if factor > 1.0:
        faster = True

    return {
        "faster": faster,
        "saved_ms": saved_ms,
        "factor": factor
    }

def max_abs_dev(a: Sequence[float], b: Sequence[float]) -> dict[str, Any]:
    if len(a) != len(b):
        raise AgreementError("Input sequences a and b must have the same length.")
    if len(a) == 0 or len(b) == 0:
        raise AgreementError("Input sequences a and b must not be empty.")

    max_abs = abs(_finite(a[0], f"a[0]") - _finite(b[0], f"b[0]"))
    best_i = 0
    for i in range(1, len(a)):
        a_finite = _finite(a[i], f"a[{i}]")
        b_finite = _finite(b[i], f"b[{i}]")
        if abs(a_finite - b_finite) > max_abs:
            max_abs = abs(a_finite - b_finite)
            best_i = i

    return {
        "max_abs": max_abs,
        "index": best_i,
        "a": a[best_i],
        "b": b[best_i],
        "n": len(a)
    }
    


def max_rel_dev(a: Sequence[float], b: Sequence[float],
                floor: float = REL_FLOOR) -> dict[str, Any]:
    if len(a) == 0 or len(b) == 0:
        raise AgreementError("Input sequences a and b must not be empty.")
    if len(a) != len(b):
        raise AgreementError("Input sequences a and b must have the same length.")

    tau = _finite(floor, "floor")
    if tau <= 0:
        raise AgreementError(f"floor {floor} is not positive.")
    
    floored = 0
    best = -1.0
    best_i = 0
    denom_min = float("inf")
    for i in range(len(a)):
        ai = _finite(a[i], f"a[{i}]")
        bi = _finite(b[i], f"b[{i}]")

        d = abs(bi)
        if d < tau:
            floored += 1
        if d < denom_min:
            denom_min = d

        r = abs(ai - bi) / max(d, tau)
        if r > best:
            best = r
            best_i = i

    return {
        "max_rel": best,
        "floored": floored,
        "n": len(a),
        "denom_min": denom_min,
        "index": best_i
    }


def top1_agreement(rows_a: Sequence[Sequence[float]],
                   rows_b: Sequence[Sequence[float]]) -> dict[str, Any]:
    if len(rows_a) == 0 or len(rows_b) == 0:
        raise AgreementError("Input sequences rows_a and rows_b must not be empty.")
    if len(rows_a) != len(rows_b):
        raise AgreementError("Input sequences rows_a and rows_b must have the same length.")

    agree = 0
    first_disagreement = None
    for k in range(len(rows_a)):
        if len(rows_a[k]) == 0 or len(rows_b[k]) == 0:
            raise AgreementError(f"Row {k} in rows_a or rows_b is empty.")
        if len(rows_a[k]) != len(rows_b[k]):
            raise AgreementError(f"Row {k} in rows_a and rows_b must have the same length.")

        max_a = -float("inf")
        max_b = -float("inf")
        ia = 0
        ib = 0
        for i in range(len(rows_a[k])):
            a = _finite(rows_a[k][i], f"rows_a[{k}][{i}]")
            b = _finite(rows_b[k][i], f"rows_b[{k}][{i}]")

            if a > max_a:
                max_a = a
                ia = i
            if b > max_b:
                max_b = b
                ib = i

        if ia == ib:
            agree += 1
        else:
            if first_disagreement is None:
                first_disagreement = k

    rate = agree / len(rows_a)
    disagreement = len(rows_a) - agree

    return {
        "agree": agree,
        "disagree": disagreement,
        "rate": rate,
        "first_disagreement": first_disagreement,
        "n": len(rows_a)
    }


def decision_margin(rows: Sequence[Sequence[float]],
                    tol: float) -> dict[str, Any]:
    if len(rows) == 0:
        raise AgreementError("Input sequence rows must not be empty.")
    if _finite(tol, "tol") < 0:
        raise AgreementError(f"tol {tol} is negative.")

    mk = []
    for k in range(len(rows)):
        if len(rows[k]) < 2:
            raise AgreementError(f"Row {k} in rows has less than 2 elements.")

        r = [_finite(x, f"rows[{k}][{index}]") for index, x in enumerate(rows[k])]
        sorted_rows = sorted(r, reverse=True)
        mk.append(sorted_rows[0] - sorted_rows[1])

    min_margin = min(mk)
    argmin = mk.index(min_margin)
    median = _percentile(mk, 50)
    mean = sum(mk) / len(mk)
    below_tol = sum(1 for margin in mk if margin < _finite(tol, "tol"))
    safe = below_tol == 0

    return {
        "min": min_margin,
        "argmin": argmin,
        "median": median,
        "mean": mean,
        "below_tol": below_tol,
        "safe": safe,
        "n": len(rows)
    }

        

#############################################################
###############  Main function starts here ##################
#############################################################

def main(
    input_path: str | Path = "benchmark_input_data.json",
    output_path: str | Path = "benchmark_results.json",
) -> None:
    in_file = Path(input_path)
    out_file = Path(output_path)

    # 1. Load synthetic data from JSON
    if not in_file.exists():
        raise FileNotFoundError(f"Input file not found: {in_file.resolve()}")

    with in_file.open("r", encoding="utf-8") as f:
        data = json.load(f)

    timings_base = data["timings_base"]
    timings_optimized = data["timings_optimized"]
    flat_logits_base = data["flat_logits_base"]
    flat_logits_opt = data["flat_logits_opt"]
    batched_scores_base = data["batched_scores_base"]
    batched_scores_opt = data["batched_scores_opt"]

    # 2. Execute metric and report functions
    report_base = latency_report(timings_base)
    report_opt = latency_report(timings_optimized)
    perf_speedup = speedup(base_ms=report_base["p50"], other_ms=report_opt["p50"])

    abs_dev = max_abs_dev(flat_logits_opt, flat_logits_base)
    rel_dev = max_rel_dev(flat_logits_opt, flat_logits_base, floor=REL_FLOOR)

    agreement = top1_agreement(batched_scores_opt, batched_scores_base)
    margin = decision_margin(batched_scores_base, tol=abs_dev["max_abs"])

    # 3. Structure output results
    results: dict[str, Any] = {
        "latency": {
            "base": report_base,
            "optimized": report_opt,
            "speedup_p50": perf_speedup,
        },
        "deviations": {
            "max_abs_dev": abs_dev,
            "max_rel_dev": rel_dev,
            "summary_sentence": deviation_sentence(abs_dev, rel_dev),
        },
        "agreement": {
            "top1_agreement": agreement,
            "decision_margin": margin,
            "decision_sentence": decision_sentence(margin, tol=abs_dev["max_abs"]),
        },
    }

    # 4. Save results to JSON
    with out_file.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    # 5. Print a console summary
    print(f"Loaded input from: {in_file.resolve()}")
    print(f"Results saved to:  {out_file.resolve()}\n")
    print("--- Summary ---")
    print(results["deviations"]["summary_sentence"])
    print(results["agreement"]["decision_sentence"])
    print(
        f"Speedup (p50): {perf_speedup['factor']:.2f}x "
        f"({perf_speedup['saved_ms']:.2f} ms saved)"
    )

if __name__ == "__main__":
    main()