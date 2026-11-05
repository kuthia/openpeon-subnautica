# /// script
# requires-python = ">=3.11"
# dependencies = ["imageio-ffmpeg==0.8.1"]
# ///
"""Measure pack audio with the registry's FFmpeg filter and check its policy."""

import argparse
from array import array
import hashlib
import json
import math
from pathlib import Path
import platform
import re
import statistics
import subprocess
import sys
import wave

import imageio_ffmpeg


ROOT = Path(__file__).resolve().parent.parent
POLICY = {
    "target_lufs_integrated": -20.0,
    "loudness_tolerance_lu": 0.1,
    "max_true_peak_dbtp": -2.0,
    "max_loudness_spread_lu": 0.2,
}


def pack_path(relative):
    path = (ROOT / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(ROOT):
        raise ValueError(f"Sound path escapes the pack: {relative}")
    return path


def decibels(value):
    return round(20 * math.log10(value), 6) if value > 0 else None


def pcm_metrics(path):
    with wave.open(str(path), "rb") as audio:
        width = audio.getsampwidth()
        channels = audio.getnchannels()
        rate = audio.getframerate()
        frames = audio.getnframes()
        if audio.getcomptype() != "NONE" or width not in (1, 2, 3, 4):
            raise ValueError(f"Unsupported PCM format: {path.name}")
        payload = audio.readframes(frames)
    if frames <= 0 or len(payload) != frames * channels * width:
        raise ValueError(f"Empty or truncated PCM: {path.name}")
    if width == 1:
        samples = [sample - 128 for sample in payload]
    elif width == 3:
        samples = [
            int.from_bytes(payload[i : i + 3], "little", signed=True)
            for i in range(0, len(payload), 3)
        ]
    else:
        samples = array("h" if width == 2 else "i")
        samples.frombytes(payload)
        if sys.byteorder != "little":
            samples.byteswap()
    full_scale = 2 ** (8 * width - 1)
    peak = max(abs(sample) for sample in samples) / full_scale
    rms = math.sqrt(math.fsum(sample * sample for sample in samples) / len(samples))
    return {
        "duration_seconds": frames / rate,
        "frames": frames,
        "sample_rate_hz": rate,
        "channels": channels,
        "bits_per_sample": 8 * width,
        "peak_dbfs": decibels(peak),
        "rms_dbfs": decibels(rms / full_scale),
    }


def measure(ffmpeg, relative, categories):
    path = pack_path(relative)
    completed = subprocess.run(
        [
            ffmpeg, "-hide_banner", "-nostats", "-i", str(path),
            "-af", "loudnorm=print_format=json", "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    match = re.search(r'\{\s*"input_i"\s*:.*?\}', completed.stderr, re.DOTALL)
    if match is None:
        raise ValueError(f"FFmpeg returned no loudness measurement: {relative}")
    raw = json.loads(match.group())
    integrated = float(raw["input_i"])
    true_peak = float(raw["input_tp"])
    if not math.isfinite(integrated) or not math.isfinite(true_peak):
        raise ValueError(f"Audio has no finite loudness measurement: {relative}")
    return {
        "file": relative,
        "categories": sorted(categories),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        **pcm_metrics(path),
        "lufs_integrated": integrated,
        "true_peak_dbtp": true_peak,
        "loudnorm_input": {key: value for key, value in raw.items() if key.startswith("input_")},
    }


def check_measurements(records):
    errors = []
    target = POLICY["target_lufs_integrated"]
    tolerance = POLICY["loudness_tolerance_lu"]
    ceiling = POLICY["max_true_peak_dbtp"]
    for record in records:
        if abs(record["lufs_integrated"] - target) > tolerance + 1e-9:
            errors.append(f'{record["file"]}: loudness is outside {target:g} +/- {tolerance:g} LUFS')
        if record["true_peak_dbtp"] > ceiling + 1e-9:
            errors.append(f'{record["file"]}: true peak exceeds {ceiling:g} dBTP')
    if not records:
        return {"passed": False, "errors": ["The manifest contains no sounds"]}, {}
    levels = [record["lufs_integrated"] for record in records]
    spread = round(max(levels) - min(levels), 6)
    if spread > POLICY["max_loudness_spread_lu"] + 1e-9:
        errors.append("Pack loudness spread exceeds the policy")
    summary = {
        "sound_count": len(records),
        "min_lufs_integrated": min(levels),
        "max_lufs_integrated": max(levels),
        "median_lufs_integrated": statistics.median(levels),
        "loudness_spread_lu": spread,
        "max_true_peak_dbtp": max(record["true_peak_dbtp"] for record in records),
    }
    return {"passed": not errors, "errors": errors}, summary


def audit():
    manifest_bytes = (ROOT / "openpeon.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    sounds = {}
    for category, entry in manifest["categories"].items():
        for sound in entry["sounds"]:
            sounds.setdefault(sound["file"], set()).add(category)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    version = subprocess.run(
        [ffmpeg, "-version"], capture_output=True, text=True, check=True,
    ).stdout.splitlines()[0]
    records = [measure(ffmpeg, relative, sounds[relative]) for relative in sorted(sounds)]
    checks, summary = check_measurements(records)
    return {
        "format_version": 1,
        "pack": {
            "name": manifest["name"],
            "version": manifest["version"],
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        },
        "tools": {
            "python": platform.python_version(),
            "imageio_ffmpeg": imageio_ffmpeg.__version__,
            "ffmpeg": version,
            "platform": platform.system(),
            "architecture": platform.machine(),
        },
        "measurement": {
            "filter": "loudnorm=print_format=json",
            "loudness_fields": ["input_i", "input_tp"],
            "pcm_metrics": "Whole-file sample peak and RMS across all channels",
            "source_files_modified": False,
            "short_term_loudness": "Not reported: these clips are shorter than the 3-second window",
        },
        "policy": POLICY,
        "summary": summary,
        "checks": checks,
        "files": records,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Write a JSON report to this path")
    parser.add_argument("--check", action="store_true", help="Fail if measured audio violates the policy")
    args = parser.parse_args()
    try:
        report = audit()
        encoded = json.dumps(report, indent=2, allow_nan=False) + "\n"
        if args.output is not None:
            protected = {ROOT / "openpeon.json"} | {pack_path(row["file"]) for row in report["files"]}
            if args.output.resolve() in protected:
                raise ValueError("The report output must not overwrite the manifest or a sound")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(encoded, encoding="utf-8")
        else:
            print(encoded, end="")
    except (OSError, ValueError, KeyError, wave.Error, subprocess.CalledProcessError) as error:
        parser.exit(2, f"Audio audit failed: {error}\n")
    if args.check and not report["checks"]["passed"]:
        for error in report["checks"]["errors"]:
            print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
