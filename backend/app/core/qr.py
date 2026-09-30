from __future__ import annotations

from io import BytesIO
from xml.sax.saxutils import escape

import qrcode
from qrcode.constants import ERROR_CORRECT_M
from qrcode.image.svg import SvgPathImage


def build_qr_svg(payload: str, *, box_size: int = 10, border: int = 6) -> str:
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(payload)
    qr.make(fit=True)

    image = qr.make_image(image_factory=SvgPathImage)
    output = BytesIO()
    image.save(output)
    svg = output.getvalue().decode("utf-8")

    svg_start = svg.find("<svg")
    insert_at = svg.find(">", svg_start) + 1
    if svg_start < 0 or insert_at <= 0:
        return svg

    metadata = (
        '<rect width="100%" height="100%" fill="#ffffff"/>'
        '<g fill="#000000">'
        f'<desc>{escape(payload)}</desc>'
    )
    svg = svg[:insert_at] + metadata + svg[insert_at:]
    return svg.replace("</svg>", "</g></svg>")
