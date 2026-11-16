"""Browser-only adapter for the canonical reconciliation engine.

This module never opens a network connection and keeps one run in Web Worker memory.
"""

from io import BytesIO
from zipfile import BadZipFile, ZipFile
import json

from decisions import assign, remove
from export_results import export_run_bytes
from normalize import DataError
from reconcile import load_run_bytes

MAX_FILE = 8_000_000
MAX_EXPANDED = 80_000_000
MAX_ENTRIES = 1000
PAGE_SIZE = 50
run = None


def _preflight(data: bytes) -> None:
    if not data or len(data) > MAX_FILE or data[:2] != b"PK":
        raise DataError("Selecciona un XLSX válido de hasta 8 MB")
    try:
        with ZipFile(BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ENTRIES or sum(i.file_size for i in infos) > MAX_EXPANDED:
                raise DataError("El libro excede los límites de seguridad")
            if any(i.file_size > MAX_EXPANDED or
                   (i.compress_size and i.file_size / i.compress_size > 1000)
                   for i in infos):
                raise DataError("El libro tiene una expansión insegura")
    except BadZipFile as exc:
        raise DataError("El XLSX está dañado") from exc


def analyze_file() -> str:
    global run
    with open("/input.xlsx", "rb") as stream:
        data = stream.read(MAX_FILE + 1)
    _preflight(data)
    candidate = load_run_bytes(data)
    run = candidate
    return page_json(1)


def page_json(page: int) -> str:
    if run is None:
        raise DataError("Carga un libro para comenzar")
    total_pages = max(1, (len(run.items) + PAGE_SIZE - 1) // PAGE_SIZE)
    if not isinstance(page, int) or page < 1 or page > total_pages:
        raise DataError("Página inválida")
    items = []
    for item in run.items[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]:
        items.append({
            "row": item.scan.row, "batch": item.scan.raw_batch,
            "part": item.scan.part, "quantity": item.scan.quantity,
            "state": item.state, "reason": item.reason,
            "candidates": [{
                "sheet": c.china.source.sheet, "row": c.china.row,
                "dn": c.china.dn, "expected": c.china.quantity,
                "issue": c.issue,
                "transit": c.transit.status if c.transit else "Sin tránsito confirmado",
            } for c in item.candidates],
        })
    data = {
        "profile": run.profile,
        "scans": len(run.scans),
        "attention_count": len(run.attention),
        "candidate_count": sum(bool(i.candidates) for i in run.items),
        "warnings": run.warnings[:20],
        "items": items,
        "page": page,
        "pages": total_pages,
        "attention": [{"sheet": a.source.sheet, "row": a.row, "reason": a.reason}
                      for a in run.attention[:100]],
        "decisions": [{
            "scan_row": d.scan_row, "china_sheet": d.china_sheet,
            "china_row": d.china_row, "dn": d.dn,
            "quantity": d.quantity, "reason": d.reason,
        } for d in run.decisions],
    }
    return json.dumps(data, ensure_ascii=False)


def add_decision(scan_row: int, china_sheet: str, china_row: int,
                 quantity: int, reason: str, page: int) -> str:
    if run is None:
        raise DataError("Carga un libro para comenzar")
    assign(run, scan_row, china_sheet, china_row, quantity, reason)
    return page_json(page)


def remove_decision(scan_row: int, china_sheet: str, china_row: int,
                    page: int) -> str:
    if run is None:
        raise DataError("Carga un libro para comenzar")
    remove(run, scan_row, china_sheet, china_row)
    return page_json(page)


def result_bytes() -> bytes:
    if run is None:
        raise DataError("Carga un libro para comenzar")
    return export_run_bytes(run)
