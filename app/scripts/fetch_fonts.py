"""Fetch Vazirmatn TTF files for PDF rendering.

This project generates PDFs using ReportLab. For correct Persian shaping and
nice typography, we prefer the Vazirmatn font. In some deployments, the image
build step has internet access; in others it might not. This script:

1) Downloads Vazirmatn-Regular.ttf and Vazirmatn-Bold.ttf into
   app/static/fonts/ (if missing)
2) Fails gracefully (never raises) if the network is unavailable.

Run:
  python -m app.scripts.fetch_fonts
"""

from __future__ import annotations

from pathlib import Path
from urllib.request import Request, urlopen


def _download(url: str, dst: Path) -> bool:
    try:
        req = Request(url, headers={"User-Agent": "water-compat/1.0"})
        with urlopen(req, timeout=30) as r:
            data = r.read()
        if not data or len(data) < 50_000:
            return False
        dst.write_bytes(data)
        return True
    except Exception:
        return False


def main() -> None:
    fonts_dir = Path(__file__).resolve().parent.parent / "static" / "fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)

    targets = {
        "Vazirmatn-Regular.ttf": [
            "https://github.com/rastikerdar/vazirmatn/raw/master/fonts/ttf/Vazirmatn-Regular.ttf",
            "https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@33.003/fonts/ttf/Vazirmatn-Regular.ttf",
            "https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@32.0.0/fonts/ttf/Vazirmatn-Regular.ttf",
        ],
        "Vazirmatn-Bold.ttf": [
            "https://github.com/rastikerdar/vazirmatn/raw/master/fonts/ttf/Vazirmatn-Bold.ttf",
            "https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@33.003/fonts/ttf/Vazirmatn-Bold.ttf",
            "https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@32.0.0/fonts/ttf/Vazirmatn-Bold.ttf",
        ],
    }

    for fname, urls in targets.items():
        dst = fonts_dir / fname
        if dst.exists() and dst.stat().st_size > 50_000:
            continue

        ok = False
        for url in urls:
            if _download(url, dst):
                ok = True
                break

        if not ok:
            # No hard-fail; PDF generator will fallback to DejaVu Sans.
            try:
                if dst.exists() and dst.stat().st_size < 50_000:
                    dst.unlink(missing_ok=True)
            except Exception:
                pass


if __name__ == "__main__":
    main()
