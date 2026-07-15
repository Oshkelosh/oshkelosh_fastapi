"""Install addons from ZIP archives or HTTPS URLs into app/addons/."""

from __future__ import annotations

import io
import importlib.util
import inspect
import ipaddress
import json
import os
import shutil
import socket
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlparse

import httpx
from packaging.specifiers import SpecifierSet
from packaging.version import Version

from app.addons.base import BaseAddon
from app.config import Settings, settings
from app.core.exceptions import ValidationError
from schemas.addon_manifest import AddonManifest

_ADDONS_ROOT = Path(__file__).resolve().parent.parent / "addons"
_MANIFEST_NAME = "oshkelosh-addon.json"
# Manifest categories are singular; on-disk discovery dirs are plural.
_CATEGORY_INSTALL_DIRS = {
    "supplier": "suppliers",
    "payment": "payments",
    "notification": "notifications",
    "frontend": "frontends",
    "tool": "tools",
}
_PRIVATE_NETWORKS = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


def _category_install_dir(category: str) -> str:
    try:
        return _CATEGORY_INSTALL_DIRS[category]
    except KeyError as exc:
        raise ValidationError(message=f"Unknown addon category: {category}") from exc


@dataclass(frozen=True)
class AddonInstallResult:
    addon_id: str
    addon_name: str
    category: str
    version: str
    restart_required: bool = True
    restart_flag_written: bool = False
    restart_flag_path: str | None = None


def get_addons_root() -> Path:
    return _ADDONS_ROOT


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _check_host_version(manifest: AddonManifest, host_version: str) -> None:
    host = Version(host_version)
    minimum = Version(manifest.min_oshkelosh_version)
    if host < minimum:
        raise ValidationError(
            message=(
                f"Addon requires Oshkelosh {manifest.min_oshkelosh_version} or newer "
                f"(host is {host_version})"
            )
        )
    if manifest.max_oshkelosh_version:
        maximum = Version(manifest.max_oshkelosh_version)
        if host > maximum:
            raise ValidationError(
                message=(
                    f"Addon supports Oshkelosh up to {manifest.max_oshkelosh_version} "
                    f"(host is {host_version})"
                )
            )


def _check_python_requires(python_requires: str) -> None:
    current = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if current not in SpecifierSet(python_requires):
        raise ValidationError(
            message=f"Addon requires Python {python_requires} (host is {current})"
        )


def _is_private_ip(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return True
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if any(ip in network for network in _PRIVATE_NETWORKS):
            return True
    return False


def normalize_addon_install_url(url: str) -> str:
    """Expand bare github.com/{owner}/{repo} URLs to the main.zip archive."""
    cleaned = url.strip()
    parsed = urlparse(cleaned)
    host = (parsed.hostname or "").lower()
    if host not in {"github.com", "www.github.com"}:
        return cleaned
    if parsed.scheme and parsed.scheme.lower() != "https":
        return cleaned

    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) != 2:
        return cleaned

    owner, repo = parts
    if repo.endswith(".git"):
        repo = repo[: -len(".git")]
    if not owner or not repo:
        return cleaned

    return f"https://github.com/{owner}/{repo}/archive/refs/heads/main.zip"


def validate_install_url(url: str, cfg: Settings) -> str:
    url = normalize_addon_install_url(url.strip())
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValidationError(message="Addon URL must use HTTPS")
    if not parsed.netloc or not parsed.hostname:
        raise ValidationError(message="Invalid addon URL")
    host = parsed.hostname.lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        raise ValidationError(message="Localhost URLs are not allowed for addon install")
    if _is_private_ip(host):
        raise ValidationError(message="Private network URLs are not allowed for addon install")
    if cfg.addon_install_allowed_hosts and host not in cfg.addon_install_allowed_hosts:
        allowed = ", ".join(cfg.addon_install_allowed_hosts)
        raise ValidationError(message=f"URL host not allowed. Permitted hosts: {allowed}")
    return url


async def download_addon_archive(url: str, cfg: Settings | None = None) -> bytes:
    cfg = cfg or settings
    from urllib.parse import urljoin

    current_url = validate_install_url(url, cfg)
    max_redirects = 10

    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=60.0) as client:
            for _ in range(max_redirects + 1):
                async with client.stream("GET", current_url) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("location")
                        if not location:
                            raise ValidationError(
                                message="Redirect response missing Location header"
                            )
                        current_url = validate_install_url(
                            urljoin(str(response.url), location),
                            cfg,
                        )
                        continue

                    response.raise_for_status()
                    content_type = (response.headers.get("content-type") or "").lower()
                    if content_type and "zip" not in content_type and "octet-stream" not in content_type:
                        raise ValidationError(
                            message=f"URL did not return a ZIP archive (content-type: {content_type})"
                        )
                    data = bytearray()
                    async for chunk in response.aiter_bytes(8192):
                        data.extend(chunk)
                        if len(data) > cfg.addon_install_max_bytes:
                            raise ValidationError(
                                message=f"Addon archive exceeds {cfg.addon_install_max_bytes} bytes"
                            )
                    if not data:
                        raise ValidationError(message="Downloaded addon archive is empty")
                    return bytes(data)

            raise ValidationError(message="Too many redirects while downloading addon")
    except httpx.HTTPError as exc:
        raise ValidationError(message=f"Failed to download addon: {exc}") from exc


def read_limited_stream(source: BinaryIO, max_bytes: int) -> bytes:
    data = bytearray()
    while True:
        chunk = source.read(8192)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > max_bytes:
            raise ValidationError(message=f"Addon archive exceeds {max_bytes} bytes")
    if not data:
        raise ValidationError(message="Uploaded addon archive is empty")
    return bytes(data)


def _safe_extract_zip(archive_bytes: bytes, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest.resolve()
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                member_path = Path(info.filename)
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise ValidationError(message=f"Unsafe path in addon archive: {info.filename}")
                target = (dest / member_path).resolve()
                if not str(target).startswith(str(dest_resolved)):
                    raise ValidationError(message=f"Unsafe path in addon archive: {info.filename}")
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
    except zipfile.BadZipFile as exc:
        raise ValidationError(message="Invalid ZIP archive") from exc


def _find_manifest_root(extract_dir: Path) -> tuple[Path, AddonManifest]:
    manifests = list(extract_dir.rglob(_MANIFEST_NAME))
    if not manifests:
        raise ValidationError(message=f"Addon archive must contain {_MANIFEST_NAME}")
    if len(manifests) > 1:
        raise ValidationError(message="Addon archive must contain exactly one manifest")
    manifest_path = manifests[0]
    addon_root = manifest_path.parent
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = AddonManifest.model_validate(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValidationError(message=f"Invalid {_MANIFEST_NAME}: {exc}") from exc
    return addon_root, manifest


def _validate_layout(addon_root: Path, extract_dir: Path, manifest: AddonManifest) -> None:
    try:
        relative = addon_root.relative_to(extract_dir)
    except ValueError as exc:
        raise ValidationError(message="Invalid addon archive layout") from exc

    parts = relative.parts
    if len(parts) == 2:
        category_dir, addon_dir = parts
        allowed_dirs = {manifest.category, _category_install_dir(manifest.category)}
        if category_dir not in allowed_dirs:
            raise ValidationError(
                message=(
                    f"Archive path {category_dir}/{addon_dir} does not match "
                    f"manifest category '{manifest.category}'"
                )
            )
        if addon_dir != manifest.addon_id:
            raise ValidationError(
                message=(
                    f"Archive folder '{addon_dir}' does not match "
                    f"manifest addon_id '{manifest.addon_id}'"
                )
            )
    elif len(parts) in (0, 1):
        # Flat root (len 0) or GitHub-style single wrapper folder (len 1).
        pass
    else:
        raise ValidationError(
            message=(
                "Addon archive layout must be '<category>/<addon_id>/...' "
                "or a single addon folder with manifest at its root"
            )
        )

    for required in ("__init__.py", "addon.py"):
        if not (addon_root / required).is_file():
            raise ValidationError(message=f"Addon archive missing required file: {required}")

    if manifest.category == "frontend" and not (addon_root / "dist" / "index.html").is_file():
        raise ValidationError(
            message="Frontend addon archive must include a built dist/index.html"
        )


def _verify_addon_class(addon_root: Path, manifest: AddonManifest) -> None:
    addon_py = addon_root / "addon.py"
    module_name = f"oshkelosh_addon_verify.{manifest.category}.{manifest.addon_id}"
    spec = importlib.util.spec_from_file_location(module_name, addon_py)
    if spec is None or spec.loader is None:
        raise ValidationError(message="Could not load addon.py for verification")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    candidates: list[type] = []
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if (
            issubclass(obj, BaseAddon)
            and obj is not BaseAddon
            and not inspect.isabstract(obj)
            and obj.__module__ == module.__name__
        ):
            candidates.append(obj)

    if len(candidates) != 1:
        raise ValidationError(
            message="addon.py must define exactly one concrete BaseAddon subclass"
        )

    instance = candidates[0]()
    if instance.addon_id != manifest.addon_id:
        raise ValidationError(
            message=(
                f"Addon class addon_id '{instance.addon_id}' "
                f"does not match manifest '{manifest.addon_id}'"
            )
        )
    if instance.addon_category != manifest.category:
        raise ValidationError(
            message=(
                f"Addon class category '{instance.addon_category}' "
                f"does not match manifest '{manifest.category}'"
            )
        )


def _write_restart_flag(manifest: AddonManifest, cfg: Settings) -> Path | None:
    flag_path = cfg.addon_install_restart_flag_path
    if flag_path is None:
        return None

    flag_path.parent.mkdir(parents=True, exist_ok=True)
    installed_at = _utc_now_iso()
    if cfg.addon_install_restart_flag_format == "text":
        payload = (
            f"addon_installed {manifest.addon_id} {manifest.category} "
            f"{manifest.version} {installed_at}\n"
        )
    else:
        payload = json.dumps(
            {
                "reason": "addon_installed",
                "addon_id": manifest.addon_id,
                "category": manifest.category,
                "version": manifest.version,
                "installed_at": installed_at,
                "host_version": cfg.app_version,
            },
            indent=2,
        ) + "\n"

    tmp_path = flag_path.with_suffix(flag_path.suffix + ".tmp")
    tmp_path.write_text(payload, encoding="utf-8")
    os.replace(tmp_path, flag_path)
    return flag_path


def _install_tree(addon_root: Path, manifest: AddonManifest, force: bool) -> Path:
    target = get_addons_root() / _category_install_dir(manifest.category) / manifest.addon_id
    if target.exists():
        if not force:
            raise ValidationError(
                message=(
                    f"Addon '{manifest.addon_id}' already exists. "
                    "Check 'Replace if exists' to upgrade."
                )
            )
        backup_root = get_addons_root() / ".backups"
        backup_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = backup_root / f"{manifest.addon_id}-{stamp}"
        if backup_path.exists():
            shutil.rmtree(backup_path)
        shutil.move(str(target), str(backup_path))

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(addon_root, target)
    return target


def _write_manifest_source_url(target: Path, source_url: str) -> None:
    """Persist normalized source_url onto the installed oshkelosh-addon.json."""
    manifest_path = target / _MANIFEST_NAME
    if not manifest_path.is_file():
        return
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw["source_url"] = source_url
    manifest_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")


def read_installed_manifest(addon_id: str, category: str) -> AddonManifest | None:
    """Load oshkelosh-addon.json for an installed addon, if present."""
    path = get_addons_root() / _category_install_dir(category) / addon_id / _MANIFEST_NAME
    if not path.is_file():
        return None
    try:
        return AddonManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, ValueError):
        return None


def install_addon_archive(
    archive_bytes: bytes,
    *,
    force: bool = False,
    write_restart_flag: bool = True,
    source_url: str | None = None,
    cfg: Settings | None = None,
) -> AddonInstallResult:
    """Validate and install an addon ZIP archive."""
    cfg = cfg or settings
    if len(archive_bytes) > cfg.addon_install_max_bytes:
        raise ValidationError(message=f"Addon archive exceeds {cfg.addon_install_max_bytes} bytes")

    with tempfile.TemporaryDirectory(prefix="oshkelosh-addon-") as tmp:
        extract_dir = Path(tmp) / "extract"
        _safe_extract_zip(archive_bytes, extract_dir)
        addon_root, manifest = _find_manifest_root(extract_dir)
        _validate_layout(addon_root, extract_dir, manifest)
        _check_host_version(manifest, cfg.app_version)
        _check_python_requires(manifest.python_requires)
        _verify_addon_class(addon_root, manifest)
        target = _install_tree(addon_root, manifest, force=force)
        if source_url:
            _write_manifest_source_url(target, source_url)

    flag_path = _write_restart_flag(manifest, cfg) if write_restart_flag else None
    return AddonInstallResult(
        addon_id=manifest.addon_id,
        addon_name=manifest.addon_name,
        category=manifest.category,
        version=manifest.version,
        restart_required=True,
        restart_flag_written=flag_path is not None,
        restart_flag_path=str(flag_path) if flag_path else None,
    )


async def install_addon_from_url(
    url: str,
    *,
    force: bool = False,
    write_restart_flag: bool = True,
    cfg: Settings | None = None,
) -> AddonInstallResult:
    cfg = cfg or settings
    normalized = validate_install_url(url, cfg)
    archive_bytes = await download_addon_archive(normalized, cfg)
    return install_addon_archive(
        archive_bytes,
        force=force,
        write_restart_flag=write_restart_flag,
        source_url=normalized,
        cfg=cfg,
    )
