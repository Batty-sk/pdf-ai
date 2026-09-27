"""Index a sample PDF with the real local embedding model and retrieve a page.

This does not call an AI API. It checks extraction, embeddings, and search.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pymupdf

from services.container import build_context


def main() -> int:
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        pdf = root / "Employee_Policy.pdf"
        document = pymupdf.open()
        page = document.new_page()
        page.insert_text((72, 72), "Employees are entitled to 20 days of annual leave.")
        document.save(pdf)
        document.close()

        ctx = build_context(root / "data")
        ctx.settings.set("similarity_threshold", "0.2")
        result = ctx.documents.index_file(pdf, None, print)
        if result.error or result.document is None:
            print(result.error or "Indexing failed")
            return 1
        hits = ctx.pipeline.retriever.search(
            "How many days of annual leave?",
            [result.document.id],
            top_k=3,
            hybrid=True,
        )
        if not hits:
            print("No passages retrieved")
            return 1
        top = hits[0]
        print(f"{top.filename} page {top.page} score {top.semantic_score:.3f}")
        print(top.text)
        if top.page != 1 or "20 days" not in top.text:
            print("Retrieved the wrong passage")
            return 1
    print("Smoke retrieval passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
