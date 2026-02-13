from __future__ import annotations

import os
import shutil
import tempfile
import urllib.request
from pathlib import Path

# CKEditor 5 (OSS) - Classic build.
# We fetch the build from jsDelivr (npm) and self-host it under /static/vendor/ckeditor5
# so the browser can cache it aggressively and avoid slow external CDNs.
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


def fetch_ckeditor() -> None:
    """Fetch and install CKEditor 5 classic build locally.

    Installs to: app/static/vendor/ckeditor5/
      - ckeditor.js
      - translations/fa.js (optional)

    The app will still run even if download fails (it will fall back to CDN in the lazy loader).
    """
    base_dir = Path(__file__).resolve().parents[1]  # app/
    target_dir = base_dir / "static" / "vendor" / "ckeditor5"
    ckjs = target_dir / "ckeditor.js"
    fa_js = target_dir / "translations" / "fa.js"

    if ckjs.exists():
        print(f"[fetch_ckeditor] already present: {ckjs}")
        return

    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "translations").mkdir(parents=True, exist_ok=True)

    tmp_dir = Path(tempfile.mkdtemp(prefix="ckeditor5_fetch_"))
    try:
        tmp_ck = tmp_dir / "ckeditor.js"
        _try_download(_candidate_urls("ckeditor.js"), tmp_ck)
        shutil.copy2(tmp_ck, ckjs)

        # Persian translation (optional)
        try:
            tmp_fa = tmp_dir / "fa.js"
            _try_download(_candidate_urls("fa.js"), tmp_fa)
            shutil.copy2(tmp_fa, fa_js)
        except Exception as e:
            print(f"[fetch_ckeditor] fa translation download failed (continuing): {e}")

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
