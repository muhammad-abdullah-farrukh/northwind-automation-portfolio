"""Turn a synthetic invoice PDF into a blurry, image-only "scan" with no text layer.

InvoiceIQ uses it to exercise the failure path: with no text layer, OpsCore returns `failed`
(`no_text_layer`), and n8n's error workflow fires.

    python -m evals.make_scanned evals/data/invoices/inv_019.pdf evals/data/invoices/inv_019_scan.pdf
"""

import argparse
import io

import pdfplumber
from fpdf import FPDF
from PIL import ImageFilter


def scan(src: str, dst: str, *, dpi: int = 110, blur: float = 1.6) -> None:
    pdf = FPDF(unit="pt")
    with pdfplumber.open(src) as doc:
        for page in doc.pages:
            image = page.to_image(resolution=dpi).original.convert("L").filter(ImageFilter.GaussianBlur(blur))
            buf = io.BytesIO()
            image.save(buf, format="JPEG", quality=55)
            pdf.add_page(format=(page.width, page.height))
            pdf.image(buf, x=0, y=0, w=page.width, h=page.height)
    pdf.output(dst)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("src")
    parser.add_argument("dst")
    args = parser.parse_args()
    scan(args.src, args.dst)
