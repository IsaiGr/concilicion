"""Atomic XLSX output with inert text and conspicuous pending states."""

from pathlib import Path
from io import BytesIO
import os
import tempfile

from openpyxl import Workbook
from openpyxl.utils.exceptions import IllegalCharacterError
from openpyxl.styles import Font, PatternFill

from data_models import Run
from normalize import DataError, validate_excel_text


def _safe(value: object) -> object:
    if isinstance(value, str):
        validate_excel_text(value, "Texto para exportación")
        value = value[:1000]
        if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n")):
            return "'" + value
    return value


def _row(sheet, values) -> None:
    try:
        sheet.append([_safe(value) for value in values])
    except IllegalCharacterError as exc:
        raise DataError("Texto para exportación: carácter no admitido por Excel") from exc


def export_run(run: Run, target: str | Path) -> Path:
    target = Path(target)
    if target.suffix.lower() != ".xlsx":
        raise DataError("El resultado debe ser .xlsx")
    if not target.parent.is_dir():
        raise DataError("La carpeta de salida no existe")
    if target.exists():
        raise DataError("La salida ya existe; elige otro nombre para conservarla")
    source_paths = {source.name.casefold() for source in run.sources}
    if target.name.casefold() in source_paths:
        raise DataError("La salida no puede usar el nombre de un archivo fuente")
    book = _build_workbook(run)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".conciliacion-", suffix=".xlsx",
                                         dir=target.parent, delete=False) as handle:
            temp = Path(handle.name)
        book.save(temp)
        os.replace(temp, target)
    except (IllegalCharacterError, UnicodeError) as exc:
        raise DataError("No se pudo exportar por texto incompatible con Excel") from exc
    except OSError as exc:
        raise DataError(f"No se pudo guardar el resultado: {type(exc).__name__}") from exc
    finally:
        book.close()
        if temp and temp.exists():
            temp.unlink()
    return target


def export_run_bytes(run: Run) -> bytes:
    """Export the same workbook without writing to the server filesystem."""
    book = _build_workbook(run)
    try:
        buffer = BytesIO()
        book.save(buffer)
        return buffer.getvalue()
    except (IllegalCharacterError, UnicodeError) as exc:
        raise DataError("No se pudo exportar por texto incompatible con Excel") from exc
    finally:
        book.close()


def _build_workbook(run: Run) -> Workbook:
    book = Workbook()
    result = book.active
    result.title = "Resultado"
    differences = book.create_sheet("Diferencias")
    decisions = book.create_sheet("Decisiones")
    sources = book.create_sheet("Fuentes")
    headers = ["Hoja escaneo", "Fila escaneo", "Batch original", "Clave batch", "Parte", "Cantidad escaneada",
               "DN candidato", "Batch China completo", "Cantidad esperada China", "Factura según China (DN No.)",
               "AF RECEIVED QTY", "AG RECEIVED QTY", "AH piezas faltantes", "Estado tránsito",
               "Cantidad confirmada", "Estado", "Motivo", "Hoja China", "Fila China",
               "Hoja tránsitos", "Fila tránsitos", "Consolidado SHA256"]
    legacy = run.profile == "legacy_3source_v1"
    if run.profile == "consolidado_3h_v1":
        headers[10:13] = ["AG RECEIVED QTY (por revisar)", "AH RECEIVED QTY (por revisar)",
                          "AI piezas faltantes (por revisar)"]
    attention_sheet = None if legacy else book.create_sheet("Atención")
    if legacy:
        headers = ["Fila escaneo", "Batch original", "Clave batch", "Parte", "Cantidad escaneada",
                   "DN candidato", "Batch China completo", "Cantidad esperada China", "Factura según China (DN No.)",
                   "Tránsito recibido (después SAP)", "Partes no recibidas", "Cantidad confirmada",
                   "Estado", "Motivo", "Fuente escaneo SHA256", "Fuente China SHA256"]
    for sheet in (result, differences):
        _row(sheet, headers)
    decision_map = {(d.scan_row, d.china_sheet, d.china_row): d for d in run.decisions}
    for item in run.items:
        candidates = item.candidates or [None]
        allocated = sum(d.quantity for d in run.decisions if d.scan_row == item.scan.row)
        for candidate in candidates:
            decision = decision_map.get((item.scan.row, candidate.china.source.sheet, candidate.china.row)) if candidate else None
            state = ("confirmado_con_excepcion" if candidate.issue else "confirmado") if decision else item.state
            reason = ((candidate.issue + "; " if candidate.issue else "") + decision.reason) if decision else (candidate.issue if candidate and candidate.issue else item.reason)
            row = [item.scan.source.sheet, item.scan.row, item.scan.raw_batch, item.scan.batch_key, item.scan.part,
                   item.scan.quantity, candidate.china.dn if candidate else "",
                   candidate.china.raw_batch if candidate else "",
                   candidate.china.quantity if candidate else "",
                   candidate.china.dn if candidate else "",
                   candidate.transit.received_af if candidate and candidate.transit else "",
                   candidate.transit.received if candidate and candidate.transit else "",
                   candidate.transit.not_received if candidate and candidate.transit else "",
                   candidate.transit.status if candidate and candidate.transit else "Sin tránsito confirmado",
                   decision.quantity if decision else 0, state, reason,
                   candidate.china.source.sheet if candidate else "", candidate.china.row if candidate else "",
                   candidate.transit.source.sheet if candidate and candidate.transit else "",
                   candidate.transit.row if candidate and candidate.transit else "",
                   item.scan.source.sha256]
            if legacy:
                row = [item.scan.row, item.scan.raw_batch, item.scan.batch_key, item.scan.part,
                       item.scan.quantity, candidate.china.dn if candidate else "",
                       candidate.china.raw_batch if candidate else "",
                       candidate.china.quantity if candidate else "",
                       candidate.china.dn if candidate else "",
                       candidate.transit.received if candidate and candidate.transit else "",
                       candidate.transit.not_received if candidate and candidate.transit else "",
                       decision.quantity if decision else 0, state, reason,
                       item.scan.source.sha256, candidate.china.source.sha256 if candidate else ""]
            _row(result, row)
            if not decision or candidate.issue:
                _row(differences, row)
        if allocated < item.scan.quantity:
            pending = [item.scan.source.sheet, item.scan.row, item.scan.raw_batch,
                               item.scan.batch_key, item.scan.part, item.scan.quantity,
                               "", "", "", "", "", "", "", "", allocated, "pendiente",
                               f"Sin asignar: {item.scan.quantity - allocated}", "", "", "", "",
                               item.scan.source.sha256]
            if legacy:
                pending = [item.scan.row, item.scan.raw_batch, item.scan.batch_key,
                           item.scan.part, item.scan.quantity, "", "", "", "", "", "",
                           allocated, "pendiente", f"Sin asignar: {item.scan.quantity - allocated}",
                           item.scan.source.sha256, ""]
            _row(differences, pending)
    if attention_sheet is not None:
        _row(attention_sheet, ["Hoja escaneo", "Fila escaneo", "Batch original", "Parte original",
                               "Cantidad original", "Estado", "Motivo", "Consolidado SHA256"])
        for record in run.attention:
            row = [record.source.sheet, record.row, record.raw_batch, "", record.raw_part,
                   record.raw_quantity, "", "", "", "", "", "", "", "", "",
                   "atencion", record.reason, "", "", "", "", record.source.sha256]
            _row(result, row)
            _row(differences, row)
            _row(attention_sheet, [record.source.sheet, record.row, record.raw_batch,
                                   record.raw_part, record.raw_quantity, "atencion",
                                   record.reason, record.source.sha256])
    _row(decisions, (["Fila escaneo", "Fila China", "DN", "Cantidad", "Motivo"] if legacy else
                     ["Hoja escaneo", "Fila escaneo", "Hoja China", "Fila China", "DN", "Cantidad", "Motivo", "Consolidado SHA256"]))
    for decision in run.decisions:
        _row(decisions, ([decision.scan_row, decision.china_row, decision.dn,
                          decision.quantity, decision.reason] if legacy else
                         [run.scans[0].source.sheet, decision.scan_row, decision.china_sheet,
                          decision.china_row, decision.dn, decision.quantity, decision.reason,
                          run.sources[0].sha256]))
    _row(sources, (["Tipo", "Archivo", "Hoja", "SHA256"] if legacy else
                   ["Tipo", "Archivo", "Hoja", "SHA256 consolidado", "Límite de procedencia"]))
    for source in run.sources:
        _row(sources, ([source.kind, source.name, source.sheet, source.sha256] if legacy else
                       [source.kind, source.name, source.sheet, source.sha256,
                        "La huella verifica solo el consolidado recibido; no verifica libros previos ni completitud de copia manual."]))
    if attention_sheet is not None and run.attention:
        _row(sources, ["Atención pendiente", len(run.attention), "", run.sources[0].sha256,
                       "Recepción incompleta: corrige una copia del consolidado y vuelve a cargarla."])
    for sheet in book:
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="18334B")
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
    if attention_sheet is not None and run.attention:
        attention_sheet.sheet_properties.tabColor = "AD463D"
        for sheet in (result, differences, attention_sheet):
            state_column = 6 if sheet is attention_sheet else 16
            for row in sheet.iter_rows(min_row=2):
                if row[state_column - 1].value == "atencion":
                    for cell in row:
                        cell.fill = PatternFill("solid", fgColor="FDEBE9")
    return book
