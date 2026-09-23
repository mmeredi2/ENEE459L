from __future__ import annotations

import statistics
from typing import Any

from bench import Bench, measured, read_first, read_text, unknown

import json

# A sample is still warm-up while it exceeds the settled rate by this fraction.
WARMUP_TOL = 0.5

# How many samples must sit strictly above a quantile before that quantile is an
# estimate rather than "the biggest number we saw, wearing a hat".
MIN_SAMPLES_ABOVE = 5

# Percentiles the record carries, in the order the schema lists them.
PERCENTILES = (50, 95, 99)

# The widest gap between neighbouring measurements, as a multiple of the typical
# gap, beyond which the sample is treated as coming from two populations.
MULTIMODAL_GAP_RATIO = 20.0

# Neither side of that gap is a mode unless it holds at least this fraction.
MIN_MODE_FRACTION = 0.10

# Below this many retained samples, modality is not a question worth answering.
MIN_SAMPLES_FOR_MODALITY = 20

# How far the last third of a run may drift from the first third, relative to
# the run's own median, before the run is not one population either.
STATIONARITY_TOL = 0.10
MIN_SAMPLES_FOR_STATIONARITY = 12

THERMAL_ZONES = "sys/devices/virtual/thermal"

POWER_RAIL_CANDIDATES = (
    "sys/bus/i2c/drivers/ina3221/1-0040/hwmon/hwmon3/in1_input",
    "sys/bus/i2c/drivers/ina3221/1-0040/iio:device0/in_power0_input",
    "sys/bus/i2c/drivers/ina3221x/1-0040/iio:device0/in_power0_input",
)

GPU_LOAD_CANDIDATES = (
    "sys/devices/platform/gpu.0/load",
    "sys/devices/gpu.0/load",
)

CPUFREQ_MIN = "sys/devices/system/cpu/cpu0/cpufreq/scaling_min_freq"
CPUFREQ_MAX = "sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq"


# ===========================================================================
# 1. The loop
# ===========================================================================
def run_timed_iterations(bench: Bench, repeats: int = 100) -> list[float]:
    bench.workload.synchronize()

    list_elapsed = []

    for _ in range(repeats):
        start = bench.clock()
        bench.workload.run()
        bench.workload.synchronize()
        end = bench.clock()
        elapsed = (end - start) * 1000000
        list_elapsed.append(elapsed)
    
    return list_elapsed


def find_warmup_boundary(samples: list[float]) -> dict[str, Any]:
    if len(samples) < 4:
        return unknown("samples", "Too few samples")

    second_half = samples[len(samples) // 2 :]
    median = statistics.median(second_half)

    if median <= 0:
        return unknown("median", "Median is not positive")

    threshold = median * (1 + WARMUP_TOL)

    discarded = 0
    for sample in samples:
        if sample > threshold:
            discarded +=1
        else:
            break

    retained = len(samples) - discarded

    return measured(
        discarded = "leading prefix above (1 + 0.5) x median of the run's second half",
        settled_rate_ms = median,
        threshold_ms = threshold,
        tolerance = WARMUP_TOL,
        retained = retained
    )



def summarize(samples: list[float]) -> dict[str, Any]:
    if not samples:
        return {
            "n": 0,
            "mean": None,
            "std": None,
            "min": None,
            "max": None,
            "p50": None,
            "p95": None,
            "p99": None,
        }

    sorted_samples = sorted(samples)

    mean = statistics.mean(sorted_samples)
    max = max(sorted_samples)
    min = min(sorted_samples)

    if len(samples) > 2:
        stdev = statistics.stdev(sorted_samples)
    else:
        stdev = 0.0

    def percentile(q: float) -> float:
        h = (n - 1) * q / 100.0
        i = int(h)

        if i == n - 1:
            return sorted_samples[i]

        return sorted_samples[i] + (h - i) * (
            sorted_samples[i + 1] - sorted_samples[i]
        )

    p50 = percentile(50)
    p95 = percentile(95)
    p99 = percentile(99)
    
    return {
        "n": len(samples),
        "mean": round(mean, 4),
        "std": round(stdev, 4),
        "min": round(min, 4),
        "max": round(max, 4),
        "p50": round(p50, 4),
        "p95": round(p95, 4),
        "p99": round(p99, 4),
    }

def is_multimodal(samples: list[float]) -> dict[str, Any]:
    if len(samples) < MIN_SAMPLES_FOR_MODALITY:
        unknown("Not enough samples")

    sorted_samples = sorted(samples)

    low = np.percentile(sorted_samples, MIN_SAMPLES_ABOVE)
    high = np.percentile(sorted_samples, 95)
    trimmed = sorted_samples[(sorted_samples >= low) & (sorted_samples <= high)]

    gaps = [trimmed[i + 1] - trimmed[i] for i in range(len(trimmed) - 1)]
    median_gap = statistics.median(gaps)

    if median_gap <= 0:
        unknown("Timer resolution is too coarse")

    widest_gap = max(gaps)
    ratio = widest_gap / median_gap

    upper = trimmed[gaps.index(widest_gap) + 1]
    lower = trimmed[gaps.index(widest_gap) - 1]

    upper_count = sum(1 for sample in sorted_samples if sample >= upper)
    lower_count = sum(1 for sample in sorted_samples if sample <= lower)

    if ratio >= 20 and upper_count >= (len(samples) * MIN_MODE_FRACTION) and lower_count >= (len(samples) * MIN_MODE_FRACTION):
        main = True
    else:
        main = False

    return {
        "value": ,
        "source": ,
        "status": main,
        "widest_gap": widest_gap,
        "median_gap": median_gap,
        "gap_ratio": ratio,
        "modes": 
    }
    

# ===========================================================================
# 7. The clock ceiling the run happened under
# ===========================================================================


def probe_power_state(bench: Bench) -> dict[str, Any]:
    result = bench.runner(["nvpmodel", "-q"])

    if result != 0 or fails():
        unknown("")

    power_mode = 
    mode_id = 

    max = read_text(bench.telemetry, CPUFREQ_MAX)
    min = read_text(bench.telemetry, CPUFREQ_MIN)

    if max is None or min is None:
        jetson_clocks = None
    elif max == min:
        jetson_clocks = True
    else:
        jetson_clocks = False

    return {
        "power_mode": power_mode,
        "mode_id": mode_id,
        "jetson_clocks": jetson_clocks,
        "scaling_max_freq": max,
        "scaling_min_freq": min
    }




def probe_telemetry(bench: Bench) -> dict[str, Any]:
    thermal_zones = read_text(THERMAL_ZONES)

    thermal_zones = thermal_zones / 1000

    for zone in thermal_zones:
        if zone <= -1000:
            thermal_zones.remove(zone)

    max_temp = max(thermal_zones) if thermal_zones else None


    read_first(bench.telemetry, INA3221)

    power_candidates = read_first(bench.telemetry, POWER_RAIL_CANDIDATES)
    if power_candidates is None:
        unknown("No candidate paths exist")
    else:
        power_mw = power_candidates

    gpu_candidates = read_first(bench.telemetry, GPU_LOAD_CANDIDATES)
    if gpu_candidates is None:
        unknown("No GPU load file found")
    else:
        gpu_load = gpu_candidates / 10

    return {
        "temperature": max_temp,
        "power": power_mw,
        "GPU_utilization": gpu_load
    }



## for debugging - uncomment the following lines for debugging.
# if __name__ == "__main__":
    # env = Bench.real()
    # out = find_warmup_boundary(samples)
    # print(out)

# for generating system_report.json
if __name__ == "__main__":
    # calling base environment
    env = Bench.real()

    # get your samples
    samples = run_timed_iterations(env, repeats=100)

    # testing measurments and probes
    report = {
        "warmup_boundary": find_warmup_boundary(samples),
        "summarize_setup": summarize(samples),
        "is_multimodal": is_multimodal(samples),
        "probe_power_state": probe_power_state(env),
        "probe_telemetry": probe_telemetry(env),
    }

    # save samples
    path = "samples_analysis.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(samples, f, indent=4)

    # save report
    path = "system_report.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=4)