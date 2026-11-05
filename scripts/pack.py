# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema==4.25.1"]
# ///
"""Build, verify, and archive the sound pack from its pinned source records."""

import argparse
from array import array
from decimal import Decimal, ROUND_HALF_UP, localcontext
import hashlib
import io
import json
from pathlib import Path
import re
import struct
import sys
import tempfile
import urllib.request
import wave
import zipfile
import zlib

import jsonschema


ROOT = Path(__file__).resolve().parent.parent
SCHEMA_SHA256 = "f3b848f0a88278ec09bd7344a68a999fc82cc1122bc1befb800cce9993a53441"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def pack_path(relative):
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT) or Path(relative).is_absolute():
        raise ValueError(f"Path escapes the pack: {relative}")
    return path


def load_pack():
    manifest = json.loads((ROOT / "openpeon.json").read_text())
    sources = json.loads((ROOT / "sources.json").read_text())
    schema_bytes = (ROOT / "schema/openpeon.schema.json").read_bytes()
    if sha256(schema_bytes) != SCHEMA_SHA256:
        raise ValueError("Pinned CESP schema checksum mismatch")
    jsonschema.validate(manifest, json.loads(schema_bytes))
    return manifest, sources


def asset_gain(asset):
    gain = asset.get("gain_millidb", 0)
    if type(gain) is not int or not -60000 <= gain <= 60000:
        raise ValueError(f"Invalid gain_millidb: {asset['file']}")
    return gain


def source_integrity(asset):
    fields = ("size", "crc32", "sha256")
    present = [f"source_{field}" in asset for field in fields]
    if any(present) and not all(present):
        raise ValueError(f"Incomplete source integrity record: {asset['file']}")
    if all(present):
        return {field: asset[f"source_{field}"] for field in fields}
    if "trim" in asset or asset_gain(asset) != 0:
        raise ValueError(f"Edited audio requires source integrity: {asset['file']}")
    return {field: asset[field] for field in fields}


def trim_bounds(asset, source_frames=None):
    if "trim" not in asset:
        return None
    trim = asset["trim"]
    if not isinstance(trim, dict) or set(trim) != {"start_frame", "end_frame"}:
        raise ValueError(f"Invalid frame trim record: {asset['file']}")
    start, end = trim["start_frame"], trim["end_frame"]
    if type(start) is not int or type(end) is not int or not 0 <= start < end:
        raise ValueError(f"Invalid frame trim bounds: {asset['file']}")
    # Even without the original WAV, its byte size bounds the possible PCM frames.
    # The exact bounds are checked against its decoded header during the build.
    if source_frames is None:
        source_frames = max(0, (source_integrity(asset)["size"] - 44) // 4)
    if end > source_frames:
        raise ValueError(f"Frame trim exceeds source audio: {asset['file']}")
    return start, end


def validate_sources(sources):
    assets = sources["assets"]
    if len({asset["file"] for asset in assets}) != len(assets):
        raise ValueError("Duplicate source records")
    voice = sources.get("voice")
    if "voice" in sources and (not isinstance(voice, str) or not voice.strip()):
        raise ValueError("Invalid source voice policy")
    for asset in assets:
        pack_path(asset["file"])
        asset_gain(asset)
        if voice is not None and asset.get("voice") != voice:
            raise ValueError(f"Source voice policy mismatch: {asset['file']}")
        for name, integrity in (("output", asset), ("source", source_integrity(asset))):
            if type(integrity["size"]) is not int or integrity["size"] <= 0:
                raise ValueError(f"Invalid {name} size: {asset['file']}")
            for field, length in (("crc32", 8), ("sha256", 64)):
                value = integrity[field]
                if not isinstance(value, str) or not re.fullmatch(rf"[0-9a-f]{{{length}}}", value):
                    raise ValueError(f"Invalid {name} {field}: {asset['file']}")
        trim_bounds(asset)


def verify_bytes(data, asset, *, source=False):
    integrity = source_integrity(asset) if source else asset
    name = "Source" if source else "Output"
    if len(data) != integrity["size"] or sha256(data) != integrity["sha256"]:
        raise ValueError(f"{name} checksum or size mismatch: {asset['file']}")
    if f"{zlib.crc32(data):08x}" != integrity["crc32"]:
        raise ValueError(f"{name} CRC32 mismatch: {asset['file']}")


def verify_pcm(audio, name):
    if audio.getsampwidth() != 2 or audio.getnchannels() != 2:
        raise ValueError(f"Expected 16-bit stereo PCM: {name}")
    if audio.getframerate() != 48000 or audio.getcomptype() != "NONE":
        raise ValueError(f"Expected uncompressed 48 kHz PCM: {name}")


def apply_gain(frames, gain, name):
    """Apply a deterministic Q32 constant gain to little-endian PCM16 samples."""
    if gain == 0:
        return frames
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_UP
        factor = int(
            ((Decimal(10) ** (Decimal(gain) / Decimal(20000))) * Decimal(1 << 32))
            .to_integral_value(rounding=ROUND_HALF_UP)
        )
    samples = array("h")
    if samples.itemsize != 2:
        raise ValueError("PCM16 processing requires 16-bit array samples")
    samples.frombytes(frames)
    if sys.byteorder != "little":
        samples.byteswap()
    for index, sample in enumerate(samples):
        value = (abs(sample) * factor + (1 << 31)) >> 32
        if sample < 0:
            value = -value
        if not -32768 <= value <= 32767:
            raise ValueError(f"Constant gain would overflow PCM16: {name}")
        samples[index] = value
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


def render_output(data, asset):
    """Verify the source, crop native frames, then apply the recorded gain."""
    gain = asset_gain(asset)
    verify_bytes(data, asset, source=True)
    if "trim" in asset or gain != 0:
        with wave.open(io.BytesIO(data), "rb") as audio:
            verify_pcm(audio, asset["file"])
            start, end = trim_bounds(asset, audio.getnframes()) or (0, audio.getnframes())
            audio.setpos(start)
            frames = audio.readframes(end - start)
            if len(frames) != (end - start) * 4:
                raise ValueError(f"Truncated source PCM: {asset['file']}")
        frames = apply_gain(frames, gain, asset["file"])
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as output:
            output.setnchannels(2)
            output.setsampwidth(2)
            output.setframerate(48000)
            output.writeframes(frames)
        data = buffer.getvalue()
    verify_bytes(data, asset)
    return data


def download_member(asset):
    """Read one public ZIP member; reject servers that ignore the byte range."""
    start = asset["offset"]
    # Local ZIP header, member name, extra fields, and compressed payload.
    length = asset["compressed_size"] + 1024
    request = urllib.request.Request(
        asset["source_url"],
        headers={"Range": f"bytes={start}-{start + length - 1}"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        content_range = response.headers.get("Content-Range", "")
        if response.status != 206 or not content_range.startswith(f"bytes {start}-"):
            raise ValueError("Source server did not honor the requested byte range")
        chunk = response.read(length + 1)
    if len(chunk) != length or len(chunk) < 30:
        raise ValueError("Incomplete ZIP member response")
    header = struct.unpack("<4s5H3I2H", chunk[:30])
    signature, flags, method = header[0], header[2], header[3]
    name_length, extra_length = header[9:11]
    if signature != b"PK\x03\x04" or flags & 1 or method != 8:
        raise ValueError("Unsupported or encrypted ZIP member")
    encoding = "utf-8" if flags & 0x800 else "cp437"
    member = chunk[30 : 30 + name_length].decode(encoding)
    if member != asset["member"]:
        raise ValueError(f"Unexpected archive member: {member}")
    payload_start = 30 + name_length + extra_length
    compressed = chunk[payload_start : payload_start + asset["compressed_size"]]
    if len(compressed) != asset["compressed_size"]:
        raise ValueError("Truncated compressed payload")
    decoder = zlib.decompressobj(-15)
    data = decoder.decompress(compressed, source_integrity(asset)["size"] + 1)
    if not decoder.eof or decoder.unconsumed_tail or decoder.unused_data:
        raise ValueError("Incomplete or oversized decompressed payload")
    verify_bytes(data, asset, source=True)
    return data


def build(sources):
    validate_sources(sources)
    for asset in sources["assets"]:
        target = pack_path(asset["file"])
        if target.exists():
            verify_bytes(target.read_bytes(), asset)
            continue
        data = render_output(download_member(asset), asset)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as output:
                temporary = Path(output.name)
                output.write(data)
            temporary.replace(target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        print(f"Fetched {asset['file']}")


def check(manifest, sources):
    validate_sources(sources)
    assets = {asset["file"]: asset for asset in sources["assets"]}
    referenced = set()
    total = 0
    for category, entry in manifest["categories"].items():
        if not entry["sounds"]:
            raise ValueError(f"Empty category in this pack: {category}")
        for sound in entry["sounds"]:
            asset = assets[sound["file"]]
            if asset["category"] != category or sound.get("sha256") != asset["sha256"]:
                raise ValueError(f"Source mapping mismatch: {category}")
            path = pack_path(sound["file"])
            data = path.read_bytes()
            verify_bytes(data, asset)
            if len(data) > 1024 * 1024:
                raise ValueError(f"Sound exceeds CESP 1 MiB limit: {path.name}")
            with wave.open(str(path), "rb") as audio:
                verify_pcm(audio, path.name)
                bounds = trim_bounds(asset)
                if bounds and audio.getnframes() != bounds[1] - bounds[0]:
                    raise ValueError(f"Output frame count differs from trim: {path.name}")
                duration = audio.getnframes() / audio.getframerate()
                if not 0 < duration <= 5:
                    raise ValueError(f"Unexpected notification duration: {path.name}")
                decoded = audio.readframes(audio.getnframes())
                if len(decoded) != audio.getnframes() * 4:
                    raise ValueError(f"Truncated output PCM: {path.name}")
                if not decoded or not any(decoded):
                    raise ValueError(f"Empty or silent audio: {path.name}")
            print(f"{category:18} {duration:5.3f}s  {len(data):7,} bytes  OK")
            referenced.add(sound["file"])
            total += len(data)
    if referenced != set(assets):
        raise ValueError("Unreferenced source assets")
    if {str(p.relative_to(ROOT)) for p in (ROOT / "sounds").iterdir()} != referenced:
        raise ValueError("Unexpected files in sounds/")
    if manifest.get("preview") not in referenced or total > 50 * 1024 * 1024:
        raise ValueError("Invalid preview or pack size")
    print(f"Valid CESP {manifest['cesp_version']}: {len(referenced)} sounds, {total:,} bytes")


def archive(manifest):
    destination = ROOT / "dist" / f"{manifest['name']}-{manifest['version']}.zip"
    destination.parent.mkdir(exist_ok=True)
    files = [p for p in ROOT.rglob("*") if p.is_file()]
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for path in sorted(files):
            relative = path.relative_to(ROOT)
            if any(part in {"dist", ".cache", ".git", ".venv", "__pycache__"} for part in relative.parts):
                continue
            info = zipfile.ZipInfo(relative.as_posix(), date_time=(2026, 11, 5, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            output.writestr(info, path.read_bytes())
    print(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["check", "build", "archive"])
    args = parser.parse_args()
    manifest, sources = load_pack()
    if args.action == "build":
        build(sources)
    check(manifest, sources)
    if args.action == "archive":
        archive(manifest)


if __name__ == "__main__":
    main()
