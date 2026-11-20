"""Write the demo's PDF statement and bills into sample_data/ (all generated from the same seeded dataset).

    python scripts/make_sample_documents.py            # needs Chrome or Edge only for the receipt photos

  sample_data/hdfc_savings_2026-09.pdf               September as the bank's PDF e-statement (import it live)
  sample_data/receipts/truffles_2026-08-19.png        receipt photos, rendered from HTML by a headless browser
  sample_data/receipts/apollo_2026-08-16.png          (the first two are already pinned in the demo database)
  sample_data/receipts/bigbasket_2026-08-18.png
  sample_data/receipts/amazon_invoice_2026-08-16.pdf  a marketplace invoice with a text layer

Every bill's total equals one August entry to the paisa, so each one has exactly one place to be pinned.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ledger_agent.datagen import demo_pdf_month, demo_receipts, generate, receipt_html, receipt_invoice_pdf  # noqa: E402

BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome", "chromium", "chromium-browser", "microsoft-edge",
]


def find_browser() -> str | None:
    for b in [os.environ.get("CHROME", ""), *BROWSERS]:
        if b and (Path(b).is_file() or shutil.which(b)):
            return shutil.which(b) or b
    return None


def render_png(browser: str, html: str, out: Path, height: int) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "receipt.html"
        page.write_text(html, encoding="utf-8")
        subprocess.run([browser, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                        f"--user-data-dir={Path(tmp) / 'profile'}", f"--window-size=500,{height}",
                        f"--screenshot={out.resolve()}", page.as_uri()], check=True, capture_output=True, timeout=60)
    if not out.is_file():
        raise SystemExit(f"the browser ran but wrote no screenshot at {out.resolve()}")


def main(out_dir: str = "sample_data") -> None:
    out = Path(out_dir)
    (out / "receipts").mkdir(parents=True, exist_ok=True)
    ds = generate(seed=7)
    name, data, _ = demo_pdf_month(ds)
    (out / name).write_bytes(data)
    print(f"wrote {out / name}")

    browser = find_browser()
    for spec in demo_receipts(ds):
        target = out / "receipts" / spec.filename
        if spec.kind == "pdf":
            target.write_bytes(receipt_invoice_pdf(spec))
        elif browser:
            render_png(browser, receipt_html(spec), target, 340 + 23 * len(spec.items))
        else:
            target = target.with_suffix(".html")
            target.write_text(receipt_html(spec), encoding="utf-8")
            print("  (no Chrome or Edge found: wrote the HTML instead; set CHROME=/path/to/browser for a PNG)")
        print(f"wrote {target}{'  [pinned in the demo database]' if spec.seeded else '  [upload it live]'}")


if __name__ == "__main__":
    main(*sys.argv[1:])
