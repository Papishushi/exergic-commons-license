#!/usr/bin/env python3
"""Validate source-facsimile metadata against the normative JSON Schema and asset bytes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

from jsonschema import Draft202012Validator, FormatChecker

import canonical_dossier_contract as contract

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas/evidence-image-metadata.schema.json"
EVIDENCE_IMAGE_DIR = ROOT / "dossiers/evidence-images"
IMAGE_EXTENSIONS = set(contract.RASTER_FACSIMILE_EXTENSIONS)


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected JSON object")
    return value


def valid_raster_bytes(path: Path) -> bool:
    """Fail closed when an allowed raster extension does not match the binary container."""
    data = path.read_bytes()
    suffix = path.suffix.lower()
    if suffix == ".png":
        return (
            len(data) >= 24
            and data.startswith(b"\x89PNG\r\n\x1a\n")
            and data[12:16] == b"IHDR"
        )
    if suffix in {".jpg", ".jpeg"}:
        return (
            len(data) >= 4
            and data[:3] == b"\xff\xd8\xff"
            and b"\xff\xd9" in data[-32:]
        )
    if suffix == ".webp":
        return (
            len(data) >= 16
            and data[:4] == b"RIFF"
            and data[8:12] == b"WEBP"
        )
    return False


def main() -> int:
    errors: list[str] = []
    schema = load_json(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    evidence_root = EVIDENCE_IMAGE_DIR.resolve()

    sidecars = sorted(EVIDENCE_IMAGE_DIR.rglob("*.json")) if EVIDENCE_IMAGE_DIR.exists() else []
    for sidecar in sidecars:
        rel = sidecar.relative_to(ROOT)
        if sidecar.is_symlink():
            errors.append(f"{rel}: source-facsimile metadata sidecar must not be a symlink")
            continue
        try:
            sidecar.resolve(strict=True).relative_to(evidence_root)
        except ValueError:
            errors.append(f"{rel}: metadata sidecar escapes dossiers/evidence-images")
            continue

        try:
            meta = load_json(sidecar)
        except (ValueError, json.JSONDecodeError) as exc:
            errors.append(str(exc))
            continue

        for violation in sorted(validator.iter_errors(meta), key=lambda err: list(err.path)):
            location = ".".join(str(part) for part in violation.path) or "<root>"
            errors.append(f"{rel}: schema violation at {location}: {violation.message}")

        asset_name = meta.get("asset")
        if not isinstance(asset_name, str) or not asset_name:
            continue
        asset_ref = Path(asset_name)
        if asset_ref.is_absolute() or asset_ref.name != asset_name or "/" in asset_name or "\\" in asset_name:
            errors.append(f"{rel}: asset must be a basename in the sidecar directory, got {asset_name!r}")
            continue

        asset = sidecar.parent / asset_name
        if not asset.is_file():
            errors.append(f"{rel}: referenced asset does not exist: {asset_name}")
            continue
        if asset.is_symlink():
            errors.append(f"{rel}: source-facsimile asset must not be a symlink: {asset_name}")
            continue
        try:
            asset.resolve(strict=True).relative_to(evidence_root)
        except ValueError:
            errors.append(f"{rel}: referenced asset escapes dossiers/evidence-images: {asset_name}")
            continue

        expected_sidecar = asset.with_suffix(".json")
        if expected_sidecar != sidecar:
            errors.append(
                f"{rel}: sidecar/asset basename mismatch; expected metadata file {expected_sidecar.name!r}"
            )

        if asset.suffix.lower() not in IMAGE_EXTENSIONS:
            errors.append(
                f"{rel}: referenced asset is not an allowed raster source-facsimile type: {asset_name}"
            )
        elif not valid_raster_bytes(asset):
            errors.append(
                f"{rel}: asset extension declares PNG/JPEG/WebP but binary bytes do not match: {asset_name}"
            )

        expected_hash = hashlib.sha256(asset.read_bytes()).hexdigest()
        if meta.get("contentSha256") != expected_hash:
            errors.append(f"{rel}: contentSha256 mismatch for {asset_name}")

        source_url = meta.get("sourceUrl")
        if isinstance(source_url, str):
            parsed = urlparse(source_url)
            if parsed.scheme != "https" or not parsed.netloc:
                errors.append(f"{rel}: sourceUrl must be an absolute HTTPS URL")

    if EVIDENCE_IMAGE_DIR.exists():
        for path in sorted(EVIDENCE_IMAGE_DIR.rglob("*")):
            if not path.is_file():
                continue
            if path.name == "README.md" or path.suffix.lower() == ".json":
                continue
            rel = path.relative_to(ROOT)
            if path.suffix.lower() not in IMAGE_EXTENSIONS:
                errors.append(
                    f"{rel}: unsupported source-facsimile file type; only PNG/JPEG/WebP raster assets are allowed"
                )
                continue
            if path.is_symlink():
                errors.append(f"{rel}: source-facsimile asset must not be a symlink")
                continue
            if not valid_raster_bytes(path):
                errors.append(f"{rel}: raster extension does not match PNG/JPEG/WebP binary bytes")
            sidecar = path.with_suffix(".json")
            if not sidecar.is_file():
                errors.append(f"{rel}: missing source-image metadata sidecar {sidecar.name}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print(f"evidence image metadata: OK ({len(sidecars)} sidecar(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
