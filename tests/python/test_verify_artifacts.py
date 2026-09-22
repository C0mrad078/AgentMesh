from __future__ import annotations

import plistlib
import struct
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.verify_artifacts import (
    digest,
    macho_architectures,
    scan_for_sensitive_content,
    verify_one,
    verify_pe_x64,
)


def test_digest_file_and_directory(tmp_path: Path) -> None:
    file1 = tmp_path / "file1.txt"
    file1.write_text("hello agentmash", encoding="utf-8")
    d1 = digest(file1)
    assert len(d1) == 64

    dir1 = tmp_path / "sample_dir"
    dir1.mkdir()
    (dir1 / "a.txt").write_text("alpha", encoding="utf-8")
    (dir1 / "b.txt").write_text("beta", encoding="utf-8")
    d_dir = digest(dir1)
    assert len(d_dir) == 64


def test_scan_for_sensitive_content_detects_secrets(tmp_path: Path) -> None:
    clean_file = tmp_path / "clean.txt"
    clean_file.write_text("Nothing sensitive here.", encoding="utf-8")
    scan_for_sensitive_content(clean_file)

    secret_file = tmp_path / "secret.txt"
    secret_file.write_text("ghp_12345678901234567890123456789012", encoding="utf-8")
    with pytest.raises(ValueError, match="secret-like material"):
        scan_for_sensitive_content(secret_file)

    dev_file = tmp_path / "dev.txt"
    dev_file.write_text("File from /Users/jhonatan/work/project", encoding="utf-8")
    with pytest.raises(ValueError, match="developer personal path"):
        scan_for_sensitive_content(dev_file)


def test_macho_and_pe_identification(tmp_path: Path) -> None:
    # 64-bit Mach-O little-endian magic 0xFEEDFACF with ARM64 CPU type 0x0100000C
    macho_arm64 = struct.pack("<II", 0xFEEDFACF, 0x0100000C)
    assert "aarch64" in macho_architectures(macho_arm64)

    # 64-bit Mach-O little-endian magic 0xFEEDFACF with x86_64 CPU type 0x01000007
    macho_x86_64 = struct.pack("<II", 0xFEEDFACF, 0x01000007)
    assert "x86_64" in macho_architectures(macho_x86_64)

    # Fake PE x64
    pe_file = tmp_path / "test.exe"
    # MZ header with offset to PE at 0x3C
    header = bytearray(b"MZ" + b"\x00" * 58 + struct.pack("<I", 64))
    # PE signature + machine x86_64 (0x8664)
    header.extend(b"PE\x00\x00" + struct.pack("<H", 0x8664))
    pe_file.write_bytes(bytes(header))
    assert verify_pe_x64(pe_file)


def test_verify_one_macos_app_structure(tmp_path: Path) -> None:
    app_dir = tmp_path / "Orquestrador.app"
    macos_dir = app_dir / "Contents" / "MacOS"
    macos_dir.mkdir(parents=True)

    plist_data = {
        "CFBundleShortVersionString": "0.1.0-rc.1",
        "CFBundleIdentifier": "com.agentmash.desktop",
    }
    with (app_dir / "Contents" / "Info.plist").open("wb") as fh:
        plistlib.dump(plist_data, fh)

    # Fake binary with arm64 Mach-O header and padding > 1024 bytes
    macho_arm64 = struct.pack("<II", 0xFEEDFACF, 0x0100000C) + b"\x00" * 2048
    (macos_dir / "orquestrador").write_bytes(macho_arm64)

    res = verify_one(app_dir, version="0.1.0-rc.1", arch="aarch64")
    assert res["version"] == "0.1.0-rc.1"
    assert res["architecture"] == "aarch64"
    assert isinstance(res["size_bytes"], (int, float))
    assert res["size_bytes"] > 1024
    assert len(str(res["sha256"])) == 64


def test_cli_execution(tmp_path: Path) -> None:
    app_dir = tmp_path / "Orquestrador.app"
    macos_dir = app_dir / "Contents" / "MacOS"
    macos_dir.mkdir(parents=True)

    plist_data = {"CFBundleShortVersionString": "0.1.0-rc.1"}
    with (app_dir / "Contents" / "Info.plist").open("wb") as fh:
        plistlib.dump(plist_data, fh)

    macho_arm64 = struct.pack("<II", 0xFEEDFACF, 0x0100000C) + b"\x00" * 2048
    (macos_dir / "orquestrador").write_bytes(macho_arm64)

    proc = subprocess.run(
        [
            sys.executable,
            "scripts/verify_artifacts.py",
            "--artifact",
            str(app_dir),
            "--version",
            "0.1.0-rc.1",
            "--arch",
            "aarch64",
            "--classification",
            "Unsigned Internal RC",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "Unsigned Internal RC" in proc.stdout
    assert "0.1.0-rc.1" in proc.stdout
