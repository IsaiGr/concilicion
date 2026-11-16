"""Bounded, read-only adapters for the three approved XLSX sources."""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import openpyxl

from data_models import China, Scan, Source, Transit
from normalize import DataError, china_batch, optional_nonnegative_int, part_key, positive_int, scan_batch, text

MAX_FILE_BYTES = 40 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 500 * 1024 * 1024
MAX_ROWS = 50_000
MAX_COLUMNS = 100


def _source(path: str | Path, kind: str, extension: str) -> Source:
    file = Path(path)
    if not file.is_file() or file.suffix.lower() != extension:
        raise DataError(f"{kind}: selecciona un archivo {extension} existente")
    size = file.stat().st_size
    if size == 0 or size > MAX_FILE_BYTES:
        raise DataError(f"{kind}: archivo vacío o mayor a {MAX_FILE_BYTES // (1024*1024)} MB")
    with file.open("rb") as stream:
        magic = stream.read(8)
        stream.seek(0)
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    has_links = False
    if magic[:2] != b"PK":
        raise DataError(f"{kind}: extensión .xlsx con contenido inválido")
    try:
        with ZipFile(file) as archive:
            infos = archive.infolist()
            if sum(info.file_size for info in infos) > MAX_UNCOMPRESSED_BYTES:
                raise DataError(f"{kind}: contenido descomprimido demasiado grande")
            if any(info.file_size > MAX_UNCOMPRESSED_BYTES or
                   (info.compress_size and info.file_size / info.compress_size > 1000)
                   for info in infos):
                raise DataError(f"{kind}: expansión insegura")
            names = [info.filename.lower() for info in infos]
            has_links = any("externallinks/" in name for name in names)
            if any("vbaproject" in name for name in names):
                raise DataError(f"{kind}: macros no admitidas")
    except BadZipFile as exc:
        raise DataError(f"{kind}: XLSX dañado") from exc
    return Source(kind, file.name, digest, "", has_links)


def _source_bytes(data: bytes, kind: str, extension: str, name: str) -> Source:
    """Validate an in-memory XLSX without creating an application-managed file."""
    if not isinstance(data, bytes) or not name.lower().endswith(extension):
        raise DataError(f"{kind}: selecciona un archivo {extension} válido")
    if not data or len(data) > MAX_FILE_BYTES:
        raise DataError(f"{kind}: archivo vacío o mayor a {MAX_FILE_BYTES // (1024*1024)} MB")
    if data[:2] != b"PK":
        raise DataError(f"{kind}: extensión .xlsx con contenido inválido")
    try:
        with ZipFile(BytesIO(data)) as archive:
            infos = archive.infolist()
            if sum(info.file_size for info in infos) > MAX_UNCOMPRESSED_BYTES:
                raise DataError(f"{kind}: contenido descomprimido demasiado grande")
            if any(info.file_size > MAX_UNCOMPRESSED_BYTES or
                   (info.compress_size and info.file_size / info.compress_size > 1000)
                   for info in infos):
                raise DataError(f"{kind}: expansión insegura")
            names = [info.filename.lower() for info in infos]
            has_links = any("externallinks/" in item for item in names)
            if any("vbaproject" in item for item in names):
                raise DataError(f"{kind}: macros no admitidas")
    except BadZipFile as exc:
        raise DataError(f"{kind}: XLSX dañado") from exc
    return Source(kind, name, hashlib.sha256(data).hexdigest(), "", has_links)


def _xlsx_rows(path: str | Path, source: Source, required: dict[str, str],
               sheet: str | None = None):
    try:
        book = openpyxl.load_workbook(path, read_only=True, data_only=False, keep_links=False)
    except Exception as exc:
        raise DataError(f"{source.kind}: XLSX ilegible: {type(exc).__name__}") from exc
    try:
        candidates = [book[sheet]] if sheet and sheet in book.sheetnames else book.worksheets[:5]
        if sheet and sheet not in book.sheetnames:
            raise DataError(f"{source.kind}: falta hoja {sheet}")
        for ws in candidates:
            if ((ws.max_row is not None and ws.max_row > MAX_ROWS) or
                    (ws.max_column is not None and ws.max_column > MAX_COLUMNS)):
                # Only the target data sheet is relevant; pivot sheets may be huge.
                continue
            iterator = ws.iter_rows()
            for row_number in range(1, 6):
                try:
                    row = next(iterator)
                except StopIteration:
                    break
                if len(row) > MAX_COLUMNS:
                    break
                headers = {text(cell.value).upper().strip(): i for i, cell in enumerate(row)}
                if all(key in headers for key in required):
                    indexes = {alias: headers[key] for key, alias in required.items()}
                    found = Source(source.kind, source.name, source.sha256, ws.title, source.has_links)

                    def bounded_rows():
                        for absolute_row, values in enumerate(iterator, row_number + 1):
                            if absolute_row > MAX_ROWS or len(values) > MAX_COLUMNS:
                                raise DataError(f"{source.kind}: hoja excede límites de filas o columnas")
                            yield values

                    yield found, row_number, indexes, bounded_rows()
                    return
        raise DataError(f"{source.kind}: faltan hoja o encabezados: {', '.join(required)}")
    finally:
        book.close()


def _field(row, index: int, label: str):
    if index >= len(row):
        return None
    cell = row[index]
    if cell.data_type == "f":
        raise DataError(f"{label}: fórmula en campo de cruce; necesita valor fijo verificado")
    return cell.value


def read_scan(path: str | Path) -> tuple[Source, list[Scan]]:
    source = _source(path, "Escaneo", ".xlsx")
    required = {"BATCH": "batch", "MATERIAL": "part", "SCAN QUANTITY": "quantity"}
    for found, header_row, indexes, rows in _xlsx_rows(path, source, required):
        result = []
        for number, row in enumerate(rows, header_row + 1):
            batch = _field(row, indexes["batch"], f"Escaneo fila {number} BATCH")
            part = _field(row, indexes["part"], f"Escaneo fila {number} MATERIAL")
            qty = _field(row, indexes["quantity"], f"Escaneo fila {number} SCAN QUANTITY")
            if not any(text(value) for value in (batch, part, qty)):
                continue
            if not all(text(value) for value in (batch, part, qty)):
                raise DataError(f"Escaneo fila {number}: batch, parte y cantidad son obligatorios")
            try:
                key, issue = scan_batch(batch), ""
            except DataError as exc:
                key, issue = "", str(exc) + "; revisión manual"
            result.append(Scan(number, text(batch), key, part_key(part),
                               positive_int(qty, f"Escaneo fila {number}"), found, issue))
        if not result:
            raise DataError("Escaneo: no hay partidas")
        return found, result
    raise DataError("Escaneo: formato inválido")


def read_china(path: str | Path, scan_keys: set[tuple[str, str]]) -> tuple[Source, list[China]]:
    source = _source(path, "China", ".xlsx")
    required = {"PART NO.": "part", "BATCH": "batch", "QUANTITY": "quantity", "DN NO.": "dn"}
    for found, header_row, indexes, rows in _xlsx_rows(path, source, required, "SPARE PARTS"):
        result = []
        for number, row in enumerate(rows, header_row + 1):
            raw_part = _field(row, indexes["part"], f"China fila {number} parte")
            raw_batch = _field(row, indexes["batch"], f"China fila {number} batch")
            if not text(raw_part) or not text(raw_batch):
                continue
            try:
                part = part_key(raw_part)
                batch = china_batch(raw_batch)
            except DataError:
                continue  # Unrelated historical rows are not candidates.
            if (part, batch) not in scan_keys:
                continue
            qty = _field(row, indexes["quantity"], f"China fila {number} cantidad")
            dn = _field(row, indexes["dn"], f"China fila {number} DN")
            if not text(dn) or not text(qty):
                raise DataError(f"China fila {number}: candidato sin DN o cantidad")
            result.append(China(number, text(raw_batch), batch, part,
                                positive_int(qty, f"China fila {number}"), text(dn), found))
        return found, result
    raise DataError("China: formato inválido")


def read_transit(path: str | Path, candidates: set[tuple[str, str]]) -> tuple[Source, list[Transit]]:
    source = _source(path, "Tránsitos", ".xlsx")
    required = {"DN": "dn", "INVOICE NO.": "invoice", "PART. NO.": "part", "QTY": "expected",
                "RECEIVED QTY": "received", "PARTS NOT RECEIVED": "not_received"}
    for found, header_row, indexes, rows in _xlsx_rows(path, source, required, "BASE GENERAL"):
        result = []
        for number, row in enumerate(rows, header_row + 1):
            dn = _field(row, indexes["dn"], f"Tránsitos fila {number} DN")
            invoice_no = _field(row, indexes["invoice"], f"Tránsitos fila {number} INVOICE NO.")
            part = _field(row, indexes["part"], f"Tránsitos fila {number} parte")
            if not text(part):
                continue
            try:
                normalized = part_key(part)
            except DataError:
                continue
            reference = text(dn) if (text(dn), normalized) in candidates else text(invoice_no)
            if (reference, normalized) not in candidates:
                continue
            issues = []
            values = []
            for key, label in (("expected", "QTY"), ("received", "RECEIVED QTY"),
                               ("not_received", "PARTS NOT RECEIVED")):
                try:
                    value = _field(row, indexes[key], f"Tránsitos fila {number} {label}")
                    values.append(optional_nonnegative_int(value, f"Tránsitos fila {number} {label}"))
                except DataError:
                    values.append(None)
                    issues.append(f"{label} no verificable (fórmula o dato inválido)")
            result.append(Transit(number, reference, normalized, *values, found, "; ".join(issues)))
        return found, result
    raise DataError("Tránsitos: formato inválido")
