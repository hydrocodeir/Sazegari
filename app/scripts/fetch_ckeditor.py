from __future__ import annotations

import os
import shutil
import tempfile
import urllib.request
from pathlib import Path

# CKEditor 5 (OSS) - Classic build.
# We self-host it under /static/vendor/ckeditor5 so the browser can cache it
# aggressively and avoid slow external CDNs.
# Source priority:
#   1) local pre-downloaded files in /static/js/ckeditor5-build-classic
#   2) CDN download fallback
#
# Default pinned version chosen for stability.
DEFAULT_VERSION = os.environ.get("CKEDITOR5_VERSION", "44.3.0")


def _candidate_urls(kind: str) -> list[str]:
    """Return download candidates for CKEditor assets.

    You can override with:
      - CKEDITOR5_JS_URL
      - CKEDITOR5_FA_URL
    """
    if kind == "ckeditor.js":
        override = os.environ.get("CKEDITOR5_JS_URL")
        if override:
            return [override]
        return [
            f"https://cdn.jsdelivr.net/npm/@ckeditor/ckeditor5-build-classic@{DEFAULT_VERSION}/build/ckeditor.js",
            f"https://unpkg.com/@ckeditor/ckeditor5-build-classic@{DEFAULT_VERSION}/build/ckeditor.js",
        ]

    if kind == "fa.js":
        override = os.environ.get("CKEDITOR5_FA_URL")
        if override:
            return [override]
        return [
            f"https://cdn.jsdelivr.net/npm/@ckeditor/ckeditor5-build-classic@{DEFAULT_VERSION}/build/translations/fa.js",
            f"https://unpkg.com/@ckeditor/ckeditor5-build-classic@{DEFAULT_VERSION}/build/translations/fa.js",
        ]

    raise ValueError(f"Unknown kind: {kind}")


def _download(url: str, out_path: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "water-compat/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(out_path, "wb") as f:
        shutil.copyfileobj(resp, f)


def _try_download(urls: list[str], out_path: Path) -> None:
    last_exc: Exception | None = None
    for url in urls:
        try:
            print(f"[fetch_ckeditor] downloading: {url}")
            _download(url, out_path)
            return
        except Exception as e:
            print(f"[fetch_ckeditor] failed: {url} ({e})")
            last_exc = e
    if last_exc:
        raise last_exc


def _try_copy_local(src: Path, out_path: Path) -> bool:
    try:
        if not src.exists():
            print(f"[fetch_ckeditor] local source not found: {src}")
            return False
        if src.stat().st_size <= 0:
            print(f"[fetch_ckeditor] local source is empty: {src}")
            return False
        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out_path)
        print(f"[fetch_ckeditor] copied local asset: {src} -> {out_path}")
        return True
    except Exception as e:
        print(f"[fetch_ckeditor] local copy failed: {src} ({e})")
        return False


def fetch_ckeditor() -> None:
    """Fetch and install CKEditor 5 classic build locally.

    Installs to: app/static/vendor/ckeditor5/
      - ckeditor.js
      - translations/fa.js (optional)

    The app will still run even if download fails (it will fall back to CDN in the lazy loader).
    """
    base_dir = Path(__file__).resolve().parents[1]  # app/
    local_dir = base_dir / "static" / "js" / "ckeditor5-build-classic"
    target_dir = base_dir / "static" / "vendor" / "ckeditor5"
    local_ckjs = local_dir / "ckeditor.js"
    local_fa_js = local_dir / "fa.js"
    ckjs = target_dir / "ckeditor.js"
    fa_js = target_dir / "translations" / "fa.js"

    if ckjs.exists() and fa_js.exists():
        print(f"[fetch_ckeditor] already present: {ckjs}, {fa_js}")
        return

    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "translations").mkdir(parents=True, exist_ok=True)

    tmp_dir = Path(tempfile.mkdtemp(prefix="ckeditor5_fetch_"))
    try:
        if not ckjs.exists():
            copied = _try_copy_local(local_ckjs, ckjs)
            if not copied:
                tmp_ck = tmp_dir / "ckeditor.js"
                _try_download(_candidate_urls("ckeditor.js"), tmp_ck)
                shutil.copy2(tmp_ck, ckjs)
        else:
            print(f"[fetch_ckeditor] already present: {ckjs}")

        # Persian translation (optional)
        if not fa_js.exists():
            copied_fa = _try_copy_local(local_fa_js, fa_js)
            if not copied_fa:
                try:
                    tmp_fa = tmp_dir / "fa.js"
                    _try_download(_candidate_urls("fa.js"), tmp_fa)
                    shutil.copy2(tmp_fa, fa_js)
                except Exception as e:
                    print(f"[fetch_ckeditor] fa translation download failed (continuing): {e}")
        else:
            print(f"[fetch_ckeditor] already present: {fa_js}")

        print(f"[fetch_ckeditor] installed into: {target_dir}")

    except Exception as e:
        print(f"[fetch_ckeditor] failed: {e}")
        # Keep system running even if download fails.

    finally:
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":
    fetch_ckeditor()
