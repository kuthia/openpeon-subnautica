# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema==4.25.1"]
# ///
"""Build, verify, and archive the sound pack from its pinned source records."""

import argparse
import hashlib
import json
from pathlib import Path
import struct
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


def verify_bytes(data, asset):
    if len(data) != asset["size"] or sha256(data) != asset["sha256"]:
        raise ValueError(f"Source checksum or size mismatch: {asset['file']}")
    if f"{zlib.crc32(data):08x}" != asset["crc32"]:
        raise ValueError(f"Source CRC32 mismatch: {asset['file']}")


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
    data = decoder.decompress(compressed, asset["size"] + 1)
    if not decoder.eof or decoder.unconsumed_tail:
        raise ValueError("Incomplete or oversized decompressed payload")
    verify_bytes(data, asset)
    return data


def build(sources):
    for asset in sources["assets"]:
        target = pack_path(asset["file"])
        if target.exists():
            verify_bytes(target.read_bytes(), asset)
            continue
        data = download_member(asset)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write(data)
        temporary.replace(target)
        print(f"Fetched {asset['file']}")


def check(manifest, sources):
    assets = {asset["file"]: asset for asset in sources["assets"]}
    if len(assets) != len(sources["assets"]):
        raise ValueError("Duplicate source records")
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
                if audio.getsampwidth() != 2 or audio.getnchannels() != 2:
                    raise ValueError(f"Expected 16-bit stereo PCM: {path.name}")
                if audio.getframerate() != 48000 or audio.getcomptype() != "NONE":
                    raise ValueError(f"Expected uncompressed 48 kHz PCM: {path.name}")
                duration = audio.getnframes() / audio.getframerate()
                if not 0 < duration <= 5:
                    raise ValueError(f"Unexpected notification duration: {path.name}")
                decoded = audio.readframes(audio.getnframes())
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
