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
        elapsed = (end - start) / 1000000
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
        discarded,
        "leading prefix above (1 + 0.5) x median of the run's second half",
        settled_rate_ms = round(median, 4),
        threshold_ms = round(threshold, 4),
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

    mean = statistics.fmean(sorted_samples)
    maximum = max(sorted_samples)
    minimum = min(sorted_samples)

    if len(samples) > 2:
        stdev = statistics.stdev(sorted_samples)
    else:
        stdev = 0

    def percentile(q: float) -> float:
        h = (len(samples) - 1) * q / 100.0
        i = int(h)

        if i == len(samples) - 1:
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
        "min": round(minimum, 4),
        "max": round(maximum, 4),
        "p50": round(p50, 4),
        "p95": round(p95, 4),
        "p99": round(p99, 4),
    }

def is_multimodal(samples: list[float]) -> dict[str, Any]:
    if len(samples) < MIN_SAMPLES_FOR_MODALITY:
        return unknown("samples", "Not enough samples")

    sorted_samples = sorted(samples)
    trim_count = int(len(sorted_samples) * .05)
    trimmed = sorted_samples[trim_count: len(sorted_samples) - trim_count]

    gaps = [trimmed[i + 1] - trimmed[i] for i in range(len(trimmed) - 1)]
    median_gap = statistics.median(gaps)

    if median_gap <= 0:
        return unknown("samples", "Timer resolution is too coarse")

    widest_gap = max(gaps)
    ratio = widest_gap / median_gap
    split_index = gaps.index(widest_gap) + trim_count

    lower = sorted_samples[:split_index + 1]
    upper = sorted_samples[split_index + 1:]

    upper_count = len(upper)
    lower_count = len(lower)

    if ratio >= MULTIMODAL_GAP_RATIO and upper_count >= (len(samples) * MIN_MODE_FRACTION) and lower_count >= (len(samples) * MIN_MODE_FRACTION):
        main = True
    else:
        main = False

    modes = [
        {
            "n": lower_count,
            "share": lower_count / len(samples),
            "median": round(statistics.median(lower), 4)
        },
        {
            "n": upper_count,
            "share": upper_count / len(samples),
            "median": round(statistics.median(upper), 4)
        }
    ]

    return measured(
        main,
        "widest trimmed gap >= 20.0x the median gap, with >= 10 percent of samples on each side",
        widest_gap_ms = round(widest_gap, 4),
        typical_gap_ms = round(median_gap, 4),
        gap_ratio = round(ratio, 4),
        modes = modes 
    )
    

# ===========================================================================
# 7. The clock ceiling the run happened under
# ===========================================================================


def probe_power_state(bench: Bench) -> dict[str, Any]:
    result = bench.runner(["nvpmodel", "-q"])

    if not result.ok:
        return unknown("nvpmodel -q", result.error)

    if result.returncode != 0:
        return unknown("nvpmodel -q", f"command returned non-zero exit code {result.returncode}")

    power_mode = None
    mode_id = None

    lines = result.stdout.splitlines()
    for line in lines:
        if "NV Power Mode:" in line:
            power_mode = line.split("NV Power Mode:", 1)[1].strip()
            next_line = lines[lines.index(line) + 1].strip()

            try:
                mode_id = int(next_line.split()[-1])
            except:
                mode_id = None
            break


    if mode_id is None or power_mode is None:
        return unknown("nvpmodel -q", "Could not parse power mode and mode ID")

    max = read_text(bench.telemetry, CPUFREQ_MAX)
    min = read_text(bench.telemetry, CPUFREQ_MIN)

    if max is None or min is None:
        jetson_clocks = None
    else:
        jetson_clocks = max == min

    return {
        "value": power_mode,
        "source": "nvpmodel -q",
        "status": "ok",
        "mode_id": mode_id,
        "jetson_clocks": jetson_clocks,
        "jetson_clocks_source": measured(f"scaling_min_freq={min}, scaling_max_freq={max}", f"{CPUFREQ_MIN} vs {CPUFREQ_MAX}",)
    }




def probe_telemetry(bench: Bench) -> dict[str, Any]:
    thermal_root = bench.telemetry / THERMAL_ZONES

    temperatures = []
    zones_read = 0
    hottest = None

    try:
        for zone in thermal_root.glob("thermal_zone*"):
            temp_path = zone / "temp"

            try:
                temp_text = temp_path.read_text().strip()
            except Exception:
                continue

            try:
                temp = int(temp_text)
            except ValueError:
                continue

            if temp is None:
                continue

            if temp <= -1000:
                continue

            temp_c = temp / 1000
            temperatures.append(temp_c)
            zones_read += 1

            if hottest is None or temp_c > hottest[1]:
                hottest = (zone.name, temp_c)
    except OSError:
        pass

    if not temperatures:
        temperature_record = unknown(f"{THERMAL_ZONES}/*/temp", "no valid thermal zone readings")
    else:
        temperature_record = measured(
            round(max(temperatures), 2),
            f"{THERMAL_ZONES}/*/temp",
            zone = hottest[0],
            zones_read = zones_read,
        )

    power_candidates = read_first(bench.telemetry, POWER_RAIL_CANDIDATES)

    if power_candidates is None:
        power_record = unknown(POWER_RAIL_CANDIDATES, "none of the documented INA3221 rail paths could be read")
    else:
        power_path, power_text = power_candidates

        try:
            power = int(power_text)
            power_record = measured(power, power_path)
        except ValueError:
            power_record = unknown(power_path, f"could not parse power value: {power_text}")

    gpu_candidates = read_first(bench.telemetry, GPU_LOAD_CANDIDATES)

    if gpu_candidates is None:
        gpu_record = unknown(GPU_LOAD_CANDIDATES, "no GPU load file found")
    else:
        gpu_path, gpu_text = gpu_candidates

        try:
            gpu_load = int(gpu_text) / 10.0

            gpu_record = measured(
                round(gpu_load, 1),
                gpu_path,
                units = "per-mille / 10",
            )
        except ValueError:
            gpu_record = unknown(gpu_path, f"could not parse GPU load value: {gpu_text}")

    return {
        "temperature_c": temperature_record,
        "power_mw": power_record,
        "gpu_utilization_percent": gpu_record,
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