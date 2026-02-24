from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import zipfile
from pathlib import Path

PARTIAL_FILE_ITEMS = ("options.txt",)
PARTIAL_FOLDER_ITEMS = ("mods", "resourcepacks", "shaderpacks")
HASH_OUTPUT_DIR = "hashes"
HASH_OUTPUT_SUFFIX = ".sha1"
DEFAULT_ZIP_PREFIX = "partial-export-metadata"


class UserCancelledError(RuntimeError):
    """Raised when the user closes a selection dialog without picking a value."""


class SourceLayoutError(RuntimeError):
    """Raised when required files or folders are missing in source root."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate metadata package for partial export/import according to docs/player-data.md"
        )
    )
    parser.add_argument(
        "--source",
        type=Path,
        help="Optional source root path. If omitted, a GUI folder picker is shown.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional output zip path. If omitted, a GUI save dialog is shown.",
    )
    return parser.parse_args()


def choose_source_root_via_gui() -> Path:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:  # pragma: no cover - depends on OS image
        raise RuntimeError(
            "Tkinter is unavailable. Install Tk support or pass --source manually."
        ) from exc

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass

    selected = filedialog.askdirectory(
        title="Select standard original client root directory",
        mustexist=True,
    )
    root.destroy()

    if not selected:
        raise UserCancelledError("Source directory selection was cancelled.")
    return Path(selected)


def choose_output_zip_via_gui(default_name: str, initial_dir: Path | None = None) -> Path:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:  # pragma: no cover - depends on OS image
        raise RuntimeError(
            "Tkinter is unavailable. Install Tk support or pass --output manually."
        ) from exc

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass

    selected = filedialog.asksaveasfilename(
        title="Select output metadata zip file",
        initialfile=default_name,
        initialdir=str(initial_dir) if initial_dir else str(Path.cwd()),
        defaultextension=".zip",
        filetypes=[("ZIP archives", "*.zip"), ("All files", "*.*")],
    )
    root.destroy()

    if not selected:
        raise UserCancelledError("Output zip selection was cancelled.")
    return Path(selected)


def resolve_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    now = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    default_name = f"{DEFAULT_ZIP_PREFIX}-{now}.zip"

    source_root = args.source if args.source else choose_source_root_via_gui()

    if args.output:
        output_zip = args.output
    else:
        output_zip = choose_output_zip_via_gui(default_name=default_name, initial_dir=Path(source_root))

    return source_root, output_zip


def validate_source_layout(source_root: Path) -> None:
    problems: list[str] = []

    for rel_path in PARTIAL_FILE_ITEMS:
        abs_path = source_root / rel_path
        if not abs_path.exists():
            problems.append(f"Missing required file: {abs_path}")
        elif not abs_path.is_file():
            problems.append(f"Required path is not a file: {abs_path}")

    for rel_path in PARTIAL_FOLDER_ITEMS:
        abs_path = source_root / rel_path
        if not abs_path.exists():
            problems.append(f"Missing required folder: {abs_path}")
        elif not abs_path.is_dir():
            problems.append(f"Required path is not a folder: {abs_path}")

    if problems:
        raise SourceLayoutError("\n".join(problems))


def compute_sha1(file_path: Path) -> str:
    digest = hashlib.sha1()
    with file_path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def build_folder_hashes(source_root: Path, folder_name: str) -> list[str]:
    folder_path = source_root / folder_name
    file_paths = sorted(
        (path for path in folder_path.rglob("*") if path.is_file()),
        key=lambda item: item.relative_to(folder_path).as_posix(),
    )

    hashes = {compute_sha1(path) for path in file_paths}
    return sorted(hashes)


def render_hash_lines(hashes: list[str]) -> str:
    if not hashes:
        return ""
    return "\n".join(hashes) + "\n"


def create_hash_artifacts(source_root: Path) -> dict[str, list[str]]:
    hashes_by_folder: dict[str, list[str]] = {}

    for folder_name in PARTIAL_FOLDER_ITEMS:
        hashes_by_folder[folder_name] = build_folder_hashes(source_root, folder_name)

    return hashes_by_folder


def write_package_zip(
    source_root: Path,
    output_zip: Path,
    hashes_by_folder: dict[str, list[str]],
) -> None:
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_zip, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for rel_path in PARTIAL_FILE_ITEMS:
            archive.write(source_root / rel_path, arcname=rel_path)

        for folder_name in PARTIAL_FOLDER_ITEMS:
            hash_relative_path = (
                Path(HASH_OUTPUT_DIR) / f"{folder_name}{HASH_OUTPUT_SUFFIX}"
            ).as_posix()
            archive.writestr(hash_relative_path, render_hash_lines(hashes_by_folder[folder_name]))


def main() -> int:
    args = parse_args()

    try:
        source_root, output_zip = resolve_paths(args)
    except UserCancelledError as exc:
        print(f"Cancelled: {exc}")
        return 1

    source_root = source_root.expanduser()
    output_zip = output_zip.expanduser()

    if output_zip.suffix.lower() != ".zip":
        output_zip = output_zip.with_suffix(".zip")

    if not source_root.exists() or not source_root.is_dir():
        print(f"Error: source root does not exist or is not a directory: {source_root}")
        return 1

    try:
        validate_source_layout(source_root)
    except SourceLayoutError as exc:
        print("Error: source root does not match required partial-export layout")
        print(exc)
        return 1

    hashes_by_folder = create_hash_artifacts(source_root)
    write_package_zip(source_root, output_zip, hashes_by_folder)

    print("Done.")
    print(f"Source root: {source_root.resolve()}")
    print(f"Output zip: {output_zip.resolve()}")
    print(f"Copied files: {len(PARTIAL_FILE_ITEMS)}")
    print(f"Folder hash files: {len(PARTIAL_FOLDER_ITEMS)}")
    print(f"Unique hashes total: {sum(len(hashes) for hashes in hashes_by_folder.values())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
