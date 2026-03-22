"""EA v2 installation script.

Copies all v2 EA ``.mq5`` and ``.mqh`` files into the user's MT5 data
folder (``MQL5/Experts/TuyulFX/`` and ``MQL5/Include/TuyulFX/``), and
optionally generates an ``.ini`` config file with the Railway backend URL
and API key pre-filled.

Usage::

    python install_ea.py
    python install_ea.py --mt5-data-dir "C:\\Users\\You\\AppData\\Roaming\\MetaQuotes\\Terminal\\<ID>\\MQL5"
    python install_ea.py --api-url https://your-app.up.railway.app --api-key YOUR_KEY

Platform:
    Windows only (auto-detect); ``--mt5-data-dir`` works on any OS.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import shutil
import sys
from pathlib import Path

# Files that live directly in the ``Experts/TuyulFX/`` directory
_EXPERT_FILES: list[str] = [
    "TuyulFX_Primary_EA.mq5",
    "TuyulFX_Portfolio_EA.mq5",
]

# Include headers that live in ``Include/TuyulFX/``
_INCLUDE_FILES: list[str] = [
    "Include/TuyulFX_Common.mqh",
    "Include/TuyulFX_Json.mqh",
    "Include/TuyulFX_Http.mqh",
    "Include/TuyulFX_RiskGuard.mqh",
]

# Default MT5 terminal data directories on Windows
_WINDOWS_MT5_ROOTS: list[str] = [
    os.path.join(os.environ.get("APPDATA", ""), "MetaQuotes", "Terminal"),
]


def _sha256(path: Path) -> str:
    """Return the hex SHA-256 digest of *path*."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _detect_mt5_data_dirs() -> list[Path]:
    """Return likely MT5 data directory candidates on Windows.

    Each MetaTrader 5 profile is stored under a hex UUID sub-folder; this
    function enumerates all of them and returns the ones that contain a
    ``MQL5`` sub-directory.
    """
    candidates: list[Path] = []
    if platform.system() != "Windows":
        return candidates

    for root_str in _WINDOWS_MT5_ROOTS:
        root = Path(root_str)
        if not root.is_dir():
            continue
        for entry in root.iterdir():
            mql5_dir = entry / "MQL5"
            if mql5_dir.is_dir():
                candidates.append(mql5_dir)
    return candidates


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="install_ea",
        description="Install TuyulFX v2 EA files into an MT5 terminal data directory.",
    )
    parser.add_argument(
        "--mt5-data-dir",
        metavar="PATH",
        help=(
            "Explicit path to the MT5 terminal data MQL5 directory "
            "(e.g. C:\\...\\MQL5).  Auto-detected on Windows when omitted."
        ),
    )
    parser.add_argument(
        "--api-url",
        metavar="URL",
        default="",
        help="Railway backend API URL (e.g. https://your-app.up.railway.app).",
    )
    parser.add_argument(
        "--api-key",
        metavar="KEY",
        default="",
        help="API key / Bearer token for the backend.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be copied without actually copying anything.",
    )
    return parser.parse_args(argv)


def _resolve_mt5_data_dir(cli_value: str | None) -> Path:
    """Return the resolved MT5 data (MQL5) directory.

    Raises:
        SystemExit: If no directory can be determined or the path does not exist.
    """
    if cli_value:
        p = Path(cli_value)
        if not p.is_dir():
            sys.exit(f"[ERROR] --mt5-data-dir does not exist: {p}")
        return p

    candidates = _detect_mt5_data_dirs()
    if not candidates:
        sys.exit(
            "[ERROR] Could not auto-detect an MT5 data directory.\n"
            "       Please supply --mt5-data-dir explicitly."
        )

    if len(candidates) == 1:
        return candidates[0]

    print("[INFO] Multiple MT5 installations detected:")
    for i, c in enumerate(candidates):
        print(f"  [{i}] {c}")
    choice_str = input("Select index [0]: ").strip() or "0"
    try:
        idx = int(choice_str)
    except ValueError:
        sys.exit("[ERROR] Invalid selection.")
    if idx < 0 or idx >= len(candidates):
        sys.exit("[ERROR] Index out of range.")
    return candidates[idx]


def _install_files(
    source_dir: Path,
    mql5_dir: Path,
    dry_run: bool,
) -> list[tuple[Path, Path, str]]:
    """Copy EA and include files to the correct MT5 sub-directories.

    Returns:
        List of ``(source, destination, sha256_hex)`` tuples for the files that
        were copied (or would be copied in dry-run mode).
    """
    experts_dir = mql5_dir / "Experts" / "TuyulFX"
    include_dir = mql5_dir / "Include" / "TuyulFX"

    if not dry_run:
        experts_dir.mkdir(parents=True, exist_ok=True)
        include_dir.mkdir(parents=True, exist_ok=True)

    results: list[tuple[Path, Path, str]] = []

    for rel in _EXPERT_FILES:
        src = source_dir / rel
        dst = experts_dir / src.name
        _copy_file(src, dst, dry_run, results)

    for rel in _INCLUDE_FILES:
        src = source_dir / rel
        dst = include_dir / src.name
        _copy_file(src, dst, dry_run, results)

    return results


def _copy_file(
    src: Path,
    dst: Path,
    dry_run: bool,
    results: list[tuple[Path, Path, str]],
) -> None:
    """Copy a single file and record its checksum."""
    if not src.is_file():
        print(f"[WARN] Source file not found, skipping: {src}")
        return

    checksum = _sha256(src)
    action = "DRY-RUN" if dry_run else "COPY"
    print(f"  [{action}] {src.name}  →  {dst}  (sha256={checksum[:12]}…)")

    if not dry_run:
        shutil.copy2(src, dst)
        # Validate integrity after copy
        actual = _sha256(dst)
        if actual != checksum:
            sys.exit(f"[ERROR] Integrity check FAILED for {dst}\n  expected={checksum}\n  actual  ={actual}")

    results.append((src, dst, checksum))


def _generate_ini(mql5_dir: Path, api_url: str, api_key: str, dry_run: bool) -> Path:
    """Write a ``.ini`` template for the Primary EA with pre-filled backend settings.

    The file is placed at ``Experts/TuyulFX/TuyulFX_Primary_EA.ini``.
    """
    ini_path = mql5_dir / "Experts" / "TuyulFX" / "TuyulFX_Primary_EA.ini"
    content = (
        "; TuyulFX Primary EA configuration\n"
        "; Generated by install_ea.py — edit as needed before attaching to a chart.\n"
        "\n"
        "[Inputs]\n"
        "; Required: obtain the Agent UUID from the Agent Manager dashboard after registering your EA.\n"
        f"AgentId=\n"
        f"ApiBaseUrl={api_url}\n"
        f"ApiKey={api_key}\n"
        "EAClass=PRIMARY\n"
        "EASubtype=BROKER\n"
        "ExecutionMode=LIVE\n"
        "MagicNumber=151515\n"
        "MaxSlippagePoints=20\n"
        "HeartbeatIntervalSec=30\n"
        "ConfigPollIntervalSec=60\n"
        "SnapshotIntervalSec=300\n"
        "MaxDailyDDPercent=4.0\n"
        "MaxTotalDDPercent=8.0\n"
        "MaxConcurrentTrades=3\n"
        "MaxLotSize=1.0\n"
        "MaxSpreadPips=3.0\n"
        "UseLegacyBridge=false\n"
        "UseHttpBridge=true\n"
    )

    action = "DRY-RUN" if dry_run else "WRITE"
    print(f"\n  [{action}] INI → {ini_path}")

    if not dry_run:
        ini_path.parent.mkdir(parents=True, exist_ok=True)
        ini_path.write_text(content, encoding="utf-8")

    return ini_path


def main(argv: list[str] | None = None) -> None:
    """Entry point for the EA installation script."""
    args = _parse_args(argv)

    source_dir = Path(__file__).parent.resolve()
    print("\n[INFO] TuyulFX v2 EA Installer")
    print(f"[INFO] Source directory : {source_dir}")

    mql5_dir = _resolve_mt5_data_dir(args.mt5_data_dir)
    print(f"[INFO] MT5 MQL5 directory: {mql5_dir}")

    if args.dry_run:
        print("[INFO] ** DRY-RUN MODE — no files will be modified **\n")

    print("\n[INFO] Installing EA files...")
    installed = _install_files(source_dir, mql5_dir, args.dry_run)

    if args.api_url or args.api_key:
        _generate_ini(mql5_dir, args.api_url, args.api_key, args.dry_run)

    if not args.dry_run:
        print(f"\n[OK] {len(installed)} file(s) installed successfully.")
        print("\n[NEXT STEPS]")
        print("  1. Open MetaTrader 5.")
        print("  2. Open Navigator → Expert Advisors → TuyulFX → TuyulFX_Primary_EA.")
        print("  3. Drag it onto a chart.")
        print("  4. Fill in AgentId (from Agent Manager), ApiBaseUrl, and ApiKey.")
        print("  5. Ensure WebRequest is allowed for your ApiBaseUrl in MT5 → Tools → Options → Expert Advisors.")
    else:
        print(f"\n[OK] Dry-run complete — {len(installed)} file(s) would be installed.")


if __name__ == "__main__":
    main()
