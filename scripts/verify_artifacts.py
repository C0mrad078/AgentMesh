#!/usr/bin/env python3
"""Verify RC artifact size, checksum, architecture, version and contents."""

from __future__ import annotations

import argparse
import hashlib
import json
import plistlib
import re
import struct
import subprocess
import sys
from pathlib import Path

MIN_ARTIFACT_BYTES = 1024
DEV_NAMES = {
    ".env",
    ".venv",
    "node_modules",
    "vite.config.js",
    "vite.config.ts",
    "playwright-report",
    "test-results",
}
SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"(?i)\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{30,}\b"),
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(rb"(?i)bearer\s+[A-Za-z0-9._-]{24,}"),
)
LOCAL_PATH_PATTERNS = (
    re.compile(rb"/(?:Users|home|private/var/folders)/[^\x00\r\n\t ]{2,}"),
    re.compile(rb"[A-Za-z]:\\(?:Users|a|b|agent)\\[^\x00\r\n\t ]{2,}", re.IGNORECASE),
    re.compile(rb"/home/runner/work/[^\x00\r\n\t ]{2,}"),
)
MACH_CPU = {0x01000007: "x86_64", 0x0100000C: "aarch64"}


def artifact_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(p for p in path.rglob("*") if p.is_file())
    raise ValueError(f"artifact does not exist: {path}")


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    if path.is_dir():
        for item in sorted(p for p in path.rglob("*") if p.is_file()):
            hasher.update(item.relative_to(path).as_posix().encode("utf-8"))
            hasher.update(b"\0")
            with item.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    hasher.update(chunk)
        return hasher.hexdigest()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def scan_for_sensitive_content(path: Path) -> None:
    for pattern in SECRET_PATTERNS + LOCAL_PATH_PATTERNS:
        overlap = b""
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                data = overlap + chunk
                if pattern.search(data):
                    category = "secret-like material" if pattern in SECRET_PATTERNS else "absolute local/runner path"
                    raise ValueError(f"{category} found in {path}")
                overlap = data[-1024:]


def macho_architectures(data: bytes) -> set[str]:
    if len(data) < 8:
        return set()
    magic = data[:4]
    if magic in (b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf"):
        endian = "<" if magic == b"\xcf\xfa\xed\xfe" else ">"
        return {MACH_CPU.get(struct.unpack(endian + "I", data[4:8])[0], "unknown")}
    if magic in (b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca"):
        endian = ">" if magic[:2] == b"\xca\xfe" else "<"
        count = struct.unpack(endian + "I", data[4:8])[0]
        result = set()
        for index in range(count):
            offset = 8 + index * 20
            if offset + 4 > len(data):
                break
            result.add(MACH_CPU.get(struct.unpack(endian + "I", data[offset : offset + 4])[0], "unknown"))
        return result
    return set()


def verify_pe_x64(path: Path) -> bool:
    with path.open("rb") as stream:
        header = stream.read(64)
        if len(header) < 64 or header[:2] != b"MZ":
            return False
        pe_offset = struct.unpack_from("<I", header, 0x3C)[0]
        stream.seek(pe_offset)
        pe = stream.read(6)
    return len(pe) == 6 and pe[:4] == b"PE\0\0" and struct.unpack_from("<H", pe, 4)[0] == 0x8664


def verify_one(path: Path, version: str, arch: str) -> dict[str, object]:
    files = artifact_files(path)
    total_size = sum(item.stat().st_size for item in files)
    if total_size < MIN_ARTIFACT_BYTES:
        raise ValueError(f"artifact is unexpectedly small ({total_size} bytes): {path}")
    for item in files:
        if any(part.lower() in DEV_NAMES for part in item.parts):
            raise ValueError(f"development-only file included: {item}")
        if item.name.lower() in {".env", ".env.local", ".env.production", "id_rsa", "id_ed25519"}:
            raise ValueError(f"secret/development file included: {item}")
        scan_for_sensitive_content(item)

    if path.suffix == ".app" or path.is_dir() and path.name.endswith(".app"):
        plist_path = path / "Contents" / "Info.plist"
        if not plist_path.is_file():
            raise ValueError(f"macOS app is missing Info.plist: {path}")
        with plist_path.open("rb") as stream:
            plist = plistlib.load(stream)
        if plist.get("CFBundleShortVersionString") != version:
            raise ValueError(f"macOS app version mismatch: {plist.get('CFBundleShortVersionString')!r}")
        executable_dir = path / "Contents" / "MacOS"
        executables = [p for p in executable_dir.iterdir() if p.is_file()] if executable_dir.is_dir() else []
        found = set().union(*(macho_architectures(p.read_bytes()[:4096]) for p in executables)) if executables else set()
        if arch not in found:
            raise ValueError(f"macOS app architecture mismatch: expected {arch}, found {sorted(found)}")
    elif path.suffix.lower() == ".exe":
        if version not in path.name:
            raise ValueError(f"Windows installer filename does not identify expected version {version}")
        if arch != "x86_64" or not verify_pe_x64(path):
            raise ValueError("Windows NSIS installer is not a valid x86_64 PE executable")
        if sys.platform == "win32":
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", f"(Get-Item -LiteralPath '{path}').VersionInfo.ProductVersion"],
                check=True,
                capture_output=True,
                text=True,
            )
            if version not in result.stdout:
                raise ValueError(f"Windows installer version metadata does not contain {version}")
    elif path.suffix.lower() == ".dmg" and version not in path.name:
        raise ValueError(f"DMG filename does not identify expected version {version}")

    return {"path": str(path), "size_bytes": total_size, "sha256": digest(path), "architecture": arch, "version": version}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, action="append", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--arch", required=True, choices=("aarch64", "x86_64"))
    parser.add_argument("--classification", default="Unsigned Internal RC")
    args = parser.parse_args()
    try:
        reports = [verify_one(p, args.version, args.arch) for p in args.artifact]
    except (OSError, ValueError) as exc:
        print(f"artifact verification failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"classification": args.classification, "artifacts": reports}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
