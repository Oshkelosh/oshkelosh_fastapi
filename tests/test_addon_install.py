"""Tests for addon ZIP/URL installation."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.config import Settings, reload_settings
from app.core.exceptions import ValidationError
from app.services import addon_install


MANIFEST = {
    "addon_id": "test_install",
    "addon_name": "Test Install",
    "addon_description": "Test addon for install",
    "category": "tool",
    "version": "1.0.0",
    "min_oshkelosh_version": "0.1.0",
    "python_requires": ">=3.11",
}

FRONTEND_MANIFEST = {
    "addon_id": "default",
    "addon_name": "Default Storefront",
    "addon_description": "Test frontend for install",
    "category": "frontend",
    "version": "1.0.0",
    "min_oshkelosh_version": "0.1.0",
    "python_requires": ">=3.11",
}

ADDON_PY = '''
from pydantic import BaseModel

from app.addons.tools.base import ToolAddon


class TestInstallConfig(BaseModel):
    pass


class TestInstallAddon(ToolAddon):
    addon_id = "test_install"
    addon_name = "Test Install"
    addon_description = "Test addon for install"
    version = "1.0.0"

    @classmethod
    def config_schema(cls):
        return TestInstallConfig

    async def initialize(self, config: dict) -> None:
        pass

    async def shutdown(self) -> None:
        pass
'''

FRONTEND_ADDON_PY = '''
from pathlib import Path

from pydantic import BaseModel

from app.addons.frontends.base import FrontendAddon


class TestFrontendConfig(BaseModel):
    pass


class TestFrontendAddon(FrontendAddon):
    addon_id = "default"
    addon_name = "Default Storefront"
    addon_description = "Test frontend for install"
    version = "1.0.0"

    @classmethod
    def config_schema(cls):
        return TestFrontendConfig

    async def initialize(self, config: dict) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    def get_static_directory(self) -> str:
        return str(Path(__file__).resolve().parent / "dist")
'''

MULTI_MODULE_ADDON_PY = '''
from pydantic import BaseModel

from app.addons.tools.base import ToolAddon
from app.addons.tools.test_install.helper import FLAG


class TestInstallConfig(BaseModel):
    pass


class TestInstallAddon(ToolAddon):
    addon_id = "test_install"
    addon_name = "Test Install"
    addon_description = "Test addon for install"
    version = "1.0.0"
    helper_flag = FLAG

    @classmethod
    def config_schema(cls):
        return TestInstallConfig

    async def initialize(self, config: dict) -> None:
        pass

    async def shutdown(self) -> None:
        pass
'''

MULTI_MODULE_HELPER_PY = 'FLAG = "from-helper-module"\n'


def _build_addon_zip(
    *,
    manifest: dict | None = None,
    nested: bool = True,
    use_plural_category_dir: bool = False,
    addon_py: str | None = None,
    extra_files: dict[str, bytes] | None = None,
) -> bytes:
    manifest = manifest or MANIFEST
    category = manifest["category"]
    addon_id = manifest["addon_id"]
    if nested:
        category_dir = (
            addon_install._category_install_dir(category)
            if use_plural_category_dir
            else category
        )
        prefix = f"{category_dir}/{addon_id}/"
    else:
        prefix = ""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{prefix}oshkelosh-addon.json", json.dumps(manifest))
        zf.writestr(f"{prefix}__init__.py", "")
        zf.writestr(f"{prefix}addon.py", addon_py if addon_py is not None else ADDON_PY)
        for path, content in (extra_files or {}).items():
            if path.startswith("../") or path.startswith(prefix) or not nested:
                zf.writestr(path, content)
            else:
                zf.writestr(f"{prefix}{path}", content)
    return buf.getvalue()


def _build_github_wrapper_zip(
    *,
    wrapper: str = "default_frontend-main",
    manifest: dict | None = None,
    addon_py: str | None = None,
    extra_files: dict[str, bytes] | None = None,
) -> bytes:
    """Simulate GitHub source archives: single top-level wrapper folder."""
    manifest = manifest or FRONTEND_MANIFEST
    prefix = f"{wrapper}/"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{prefix}oshkelosh-addon.json", json.dumps(manifest))
        zf.writestr(f"{prefix}__init__.py", "")
        zf.writestr(f"{prefix}addon.py", addon_py if addon_py is not None else FRONTEND_ADDON_PY)
        for path, content in (extra_files or {}).items():
            zf.writestr(f"{prefix}{path}", content)
    return buf.getvalue()


@pytest.fixture
def install_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "addons"
    root.mkdir()
    monkeypatch.setattr(addon_install, "_ADDONS_ROOT", root)
    monkeypatch.setattr(addon_install, "get_addons_root", lambda: root)
    return root


@pytest.fixture
def install_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    reload_settings()
    cfg = Settings(
        app_version="0.1.0",
        addon_install_restart_flag_file=str(tmp_path / "restart.flag"),
        addon_install_restart_flag_format="json",
    )
    monkeypatch.setattr(addon_install, "settings", cfg)
    return cfg


def test_install_valid_zip(install_root: Path, install_settings: Settings):
    data = _build_addon_zip()
    result = addon_install.install_addon_archive(data, cfg=install_settings)

    target = install_root / "tools" / "test_install"
    assert target.is_dir()
    assert (target / "addon.py").is_file()
    assert result.addon_id == "test_install"
    assert result.restart_required is True
    assert result.restart_flag_written is True
    assert install_settings.addon_install_restart_flag_path is not None
    flag = json.loads(install_settings.addon_install_restart_flag_path.read_text())
    assert flag["addon_id"] == "test_install"
    assert flag["host_version"] == "0.1.0"


def test_install_multimodule_sibling_imports(install_root: Path, install_settings: Settings):
    """Sibling absolute imports (as Printful uses) must verify from the extract tree."""
    data = _build_addon_zip(
        addon_py=MULTI_MODULE_ADDON_PY,
        extra_files={"helper.py": MULTI_MODULE_HELPER_PY.encode()},
    )
    result = addon_install.install_addon_archive(data, cfg=install_settings)
    assert result.addon_id == "test_install"
    assert (install_root / "tools" / "test_install" / "helper.py").is_file()
    # Temp verify modules must not shadow the installed package path permanently.
    assert "app.addons.tools.test_install" not in __import__("sys").modules


def test_reject_zip_slip(install_root: Path, install_settings: Settings):
    data = _build_addon_zip(
        extra_files={"../evil.txt": b"bad"},
    )
    with pytest.raises(ValidationError, match="Unsafe path"):
        addon_install.install_addon_archive(data, cfg=install_settings)


def test_reject_incompatible_host_version(install_root: Path, install_settings: Settings):
    data = _build_addon_zip(
        manifest={**MANIFEST, "min_oshkelosh_version": "99.0.0"},
    )
    with pytest.raises(ValidationError, match="requires Oshkelosh"):
        addon_install.install_addon_archive(data, cfg=install_settings)


def test_reject_duplicate_without_force(install_root: Path, install_settings: Settings):
    data = _build_addon_zip()
    addon_install.install_addon_archive(data, cfg=install_settings)
    with pytest.raises(ValidationError, match="already exists"):
        addon_install.install_addon_archive(data, cfg=install_settings)


def test_install_with_force_replaces(install_root: Path, install_settings: Settings):
    data = _build_addon_zip()
    addon_install.install_addon_archive(data, cfg=install_settings)
    result = addon_install.install_addon_archive(data, force=True, cfg=install_settings)
    assert result.addon_id == "test_install"
    backups = list((install_root / ".backups").iterdir())
    assert len(backups) == 1


def test_reject_manifest_category_mismatch(install_root: Path, install_settings: Settings):
    data = _build_addon_zip(manifest={**MANIFEST, "category": "payment"})
    with pytest.raises(ValidationError, match="does not match"):
        addon_install.install_addon_archive(data, cfg=install_settings)


def test_install_root_layout_zip(install_root: Path, install_settings: Settings):
    data = _build_addon_zip(nested=False)
    result = addon_install.install_addon_archive(data, cfg=install_settings)
    assert result.category == "tool"
    assert (install_root / "tools" / "test_install" / "addon.py").is_file()


def test_install_plural_category_dir_zip(install_root: Path, install_settings: Settings):
    data = _build_addon_zip(use_plural_category_dir=True)
    result = addon_install.install_addon_archive(data, cfg=install_settings)
    assert result.addon_id == "test_install"
    assert (install_root / "tools" / "test_install" / "addon.py").is_file()


def test_install_github_wrapper_frontend_zip(install_root: Path, install_settings: Settings):
    data = _build_github_wrapper_zip(
        extra_files={"dist/index.html": b"<html>ok</html>"},
    )
    result = addon_install.install_addon_archive(data, cfg=install_settings)
    assert result.addon_id == "default"
    assert result.category == "frontend"
    target = install_root / "frontends" / "default"
    assert (target / "addon.py").is_file()
    assert (target / "oshkelosh-addon.json").is_file()
    assert (target / "dist" / "index.html").is_file()


def test_reject_frontend_missing_dist(install_root: Path, install_settings: Settings):
    data = _build_github_wrapper_zip()
    with pytest.raises(ValidationError, match="dist/index.html"):
        addon_install.install_addon_archive(data, cfg=install_settings)


def test_restart_flag_skipped_when_unconfigured(install_root: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = Settings(app_version="0.1.0", addon_install_restart_flag_file="")
    monkeypatch.setattr(addon_install, "settings", cfg)
    data = _build_addon_zip()
    result = addon_install.install_addon_archive(data, cfg=cfg)
    assert result.restart_flag_written is False


def test_restart_flag_default_path(install_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    flag_path = tmp_path / "data" / "restart.flag"
    cfg = Settings(app_version="0.1.0", addon_install_restart_flag_file=str(flag_path))
    monkeypatch.setattr(addon_install, "settings", cfg)
    data = _build_addon_zip()
    result = addon_install.install_addon_archive(data, cfg=cfg)
    assert result.restart_flag_written is True
    assert flag_path.is_file()
    flag = json.loads(flag_path.read_text())
    assert flag["addon_id"] == "test_install"


def test_validate_install_url_rejects_http(install_settings: Settings):
    with pytest.raises(ValidationError, match="HTTPS"):
        addon_install.validate_install_url("http://example.com/addon.zip", install_settings)


def test_normalize_github_repo_url_to_main_zip():
    expected = "https://github.com/Oshkelosh/stripe/archive/refs/heads/main.zip"
    assert addon_install.normalize_addon_install_url(
        "https://github.com/Oshkelosh/stripe"
    ) == expected
    assert addon_install.normalize_addon_install_url(
        "https://github.com/Oshkelosh/stripe/"
    ) == expected
    assert addon_install.normalize_addon_install_url(
        "https://github.com/Oshkelosh/stripe.git"
    ) == expected
    assert addon_install.normalize_addon_install_url(
        "https://www.github.com/Oshkelosh/stripe"
    ) == expected


def test_normalize_leaves_non_repo_urls_unchanged():
    archive = "https://github.com/Oshkelosh/stripe/archive/refs/heads/main.zip"
    assert addon_install.normalize_addon_install_url(archive) == archive
    other = "https://example.com/addons/test.zip"
    assert addon_install.normalize_addon_install_url(other) == other
    release = "https://github.com/Oshkelosh/stripe/releases/download/v1.0.0/stripe.zip"
    assert addon_install.normalize_addon_install_url(release) == release


def test_validate_install_url_expands_github_repo(
    install_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(addon_install, "_is_private_ip", lambda host: False)
    result = addon_install.validate_install_url(
        "https://github.com/Oshkelosh/stripe",
        install_settings,
    )
    assert result == "https://github.com/Oshkelosh/stripe/archive/refs/heads/main.zip"


@pytest.mark.asyncio
async def test_install_from_url(install_root: Path, install_settings: Settings):
    zip_bytes = _build_addon_zip()

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "application/zip"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def raise_for_status(self):
            return None

        async def aiter_bytes(self, chunk_size: int):
            yield zip_bytes

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def stream(self, method: str, url: str):
            assert method == "GET"
            return FakeResponse()

    url = "https://example.com/addons/test.zip"
    with patch("app.services.addon_install.validate_install_url", return_value=url):
        with patch("app.services.addon_install.httpx.AsyncClient", FakeClient):
            result = await addon_install.install_addon_from_url(
                url,
                cfg=install_settings,
            )

    assert result.addon_id == "test_install"
    assert (install_root / "tools" / "test_install").is_dir()
    installed = addon_install.read_installed_manifest("test_install", "tool")
    assert installed is not None
    assert installed.source_url == url


def test_install_archive_persists_source_url_override(
    install_root: Path,
    install_settings: Settings,
):
    data = _build_addon_zip()
    source = "https://github.com/Oshkelosh/example"
    addon_install.install_addon_archive(
        data,
        cfg=install_settings,
        source_url=source,
    )
    installed = addon_install.read_installed_manifest("test_install", "tool")
    assert installed is not None
    assert installed.source_url == source


def test_read_installed_manifest_missing(install_root: Path):
    assert addon_install.read_installed_manifest("nope", "tool") is None


def test_install_archive_respects_write_restart_flag_false(
    install_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    cfg = Settings(
        app_version="0.1.0",
        addon_install_restart_flag_file=str(tmp_path / "restart.flag"),
    )
    monkeypatch.setattr(addon_install, "settings", cfg)
    data = _build_addon_zip()
    result = addon_install.install_addon_archive(data, cfg=cfg, write_restart_flag=False)
    assert result.restart_flag_written is False
    assert not (tmp_path / "restart.flag").exists()
