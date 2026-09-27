"""Small PDFs generated for tests."""

from __future__ import annotations

from pathlib import Path

import pymupdf


def write_text_pdf(path: Path, lines: list[str]) -> None:
    document = pymupdf.open()
    page = document.new_page()
    y = 72
    for line in lines:
        page.insert_text((72, y), line, fontsize=12)
        y += 20
        if y > 760:
            page = document.new_page()
            y = 72
    document.save(path)
    document.close()


def write_image_only_pdf(path: Path) -> None:
    source = pymupdf.open()
    page = source.new_page()
    page.insert_text((72, 72), "Scanned leave policy grants 15 days.")
    pixmap = page.get_pixmap()
    source.close()
    document = pymupdf.open()
    image_page = document.new_page(width=pixmap.width, height=pixmap.height)
    image_page.insert_image(image_page.rect, pixmap=pixmap)
    document.save(path)
    document.close()


def write_locked_pdf(path: Path, password: str = "secret") -> None:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Parking permits are issued for one year.")
    document.save(
        path,
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw=password,
        user_pw=password,
    )
    document.close()
