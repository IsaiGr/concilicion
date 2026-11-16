"""Read a bounded consolidated XLSX using one explicit, versioned layout."""

from pathlib import Path
from io import BytesIO
import openpyxl

from data_models import AttentionRow, China, Scan, Source, Transit
from normalize import DataError, china_batch, optional_nonnegative_int, part_key, positive_int, scan_batch, text
from readers import _field, _source, _source_bytes, MAX_COLUMNS, MAX_ROWS

PROFILES = {
    "Escaneo": {1: "BATCH", 4: "PART NUMBER", 6: "QTY SCAN"},
    "China Free WK00": {10: "PART NO.", 11: "QTY", 16: "BATCH NO.", 18: "DN NO."},
    "China WK": {7: "PART NO.", 8: "QUANTITY", 11: "BATCH", 15: "DN NO."},
    "Tránsitos": {13: "INVOICE NO.", 14: "DN", 18: "PART. NO.", 20: "QTY",
                  32: "RECEIVED QTY", 33: "RECEIVED QTY", 34: "PARTS NOT RECEIVED"},
}

THREE_SHEET_PROFILES = {
    "Escaneo": {1: "BATCH", 4: "MATERIAL", 6: "SCAN QUANTITY"},
    "China": {7: "PART NO.", 8: "QUANTITY", 11: "BATCH", 15: "DN NO."},
    "Tránsitos": {13: "INVOICE NO.", 14: "DN", 19: "PART. NO.", 21: "QTY",
                  33: "RECEIVED QTY", 34: "RECEIVED QTY", 35: "PARTS NOT RECEIVED"},
}

LAYOUTS = {"consolidado_4h_v1": PROFILES, "consolidado_3h_v1": THREE_SHEET_PROFILES}
REQUIRED_ROLES = {
    "consolidado_4h_v1": ("Escaneo", "China Free WK00", "Tránsitos"),
    "consolidado_3h_v1": tuple(THREE_SHEET_PROFILES),
}

CHINA_COLUMNS = {
    "China Free WK00": (10, 16, 11, 18),
    "China WK": (7, 11, 8, 15),
    "China": (7, 11, 8, 15),
}

TRANSIT_COLUMNS = {
    "consolidado_4h_v1": ((20, "QTY"), (32, "AF RECEIVED QTY"),
                           (33, "AG RECEIVED QTY"), (34, "AH PARTS NOT RECEIVED")),
    "consolidado_3h_v1": ((21, "QTY"), (33, "AG RECEIVED QTY"),
                           (34, "AH RECEIVED QTY"), (35, "AI PARTS NOT RECEIVED")),
}


def _header(value):
    return " ".join(text(value).upper().split())


def _raw(value):
    return "" if value is None else str(value)


def _get(row, column, label):
    return _field(row, column - 1, label)


def _quantity(value, label):
    try:
        return positive_int(value, label), ""
    except DataError as exc:
        return 0, str(exc)


def _match_layout(book):
    matches = {layout: {} for layout in LAYOUTS}
    for ws in book.worksheets:
        if ws.max_row and ws.max_row > MAX_ROWS or ws.max_column and ws.max_column > MAX_COLUMNS:
            raise DataError(f"Hoja {ws.title}: excede 50,000 filas o 100 columnas")
        for number, cells in enumerate(ws.iter_rows(max_row=5), 1):
            if len(cells) > MAX_COLUMNS:
                raise DataError(f"Hoja {ws.title}: excede 100 columnas")
            headers = [_header(cell.value) for cell in cells]
            found = False
            for layout, profiles in LAYOUTS.items():
                roles = [role for role, profile in profiles.items()
                         if all(len(headers) >= col and headers[col - 1] == label
                                for col, label in profile.items())]
                if len(roles) > 1:
                    raise DataError(f"Hoja {ws.title}: rol ambiguo")
                if roles:
                    role = roles[0]
                    if role in matches[layout] and matches[layout][role][0] != ws:
                        raise DataError(f"Rol {role} ambiguo: hojas duplicadas")
                    matches[layout][role] = (ws, number)
                    found = True
            if found:
                break
    complete = [layout for layout, roles in REQUIRED_ROLES.items()
                if all(role in matches[layout] for role in roles)]
    if len(complete) != 1:
        missing = [role for role in THREE_SHEET_PROFILES if role not in matches["consolidado_3h_v1"]]
        if missing:
            raise DataError("Consolidado: faltan hojas o encabezados para " + ", ".join(missing))
        raise DataError("Consolidado: perfiles de hojas ambiguos o mezclados")
    selected = complete[0]
    # A complete layout plus a distinct role from another layout is a mixed workbook.
    other = next(layout for layout in LAYOUTS if layout != selected)
    selected_sheets = {ws for ws, _ in matches[selected].values()}
    if any(ws not in selected_sheets for ws, _ in matches[other].values()):
        raise DataError("Consolidado: perfiles de hojas ambiguos o mezclados")
    # A populated unrecognized sheet could be an invalid optional China WK;
    # reject it instead of silently treating its parts as absent. For the old
    # profile only, a sheet with no rows after its first heading is empty even
    # when that heading was edited, so it contributes no candidates.
    for ws in book.worksheets:
        if ws in selected_sheets:
            continue
        first_data_row = 2 if selected == "consolidado_4h_v1" else 1
        if any(any(text(cell.value) for cell in row)
               for row in ws.iter_rows(min_row=first_data_row)):
            raise DataError(f"Consolidado: hoja {ws.title} con estructura no reconocida")
    return selected, matches[selected]


def _secondary_china_header(row, columns):
    """Recognize the translated second heading without dropping an ordinary record."""
    markers = {"PART NO.", "PART NUMBER", "QUANTITY", "BATCH", "DN NO.",
               "物料号", "零件号", "数量", "批次", "发货单号"}
    return sum(_header(row[col - 1].value) in markers
               for col in columns if len(row) >= col) >= 2


def read_consolidated(path: str | Path):
    physical = _source(path, "Consolidado", ".xlsx")
    try:
        book = openpyxl.load_workbook(path, read_only=True, data_only=False, keep_links=False)
    except Exception as exc:
        raise DataError(f"Consolidado: XLSX ilegible: {type(exc).__name__}") from exc
    try:
        return _parse_consolidated(book, physical)
    finally:
        book.close()


def read_consolidated_bytes(data: bytes):
    physical = _source_bytes(data, "Consolidado", ".xlsx", "Consolidado.xlsx")
    try:
        book = openpyxl.load_workbook(BytesIO(data), read_only=True,
                                      data_only=False, keep_links=False)
    except Exception as exc:
        raise DataError(f"Consolidado: XLSX ilegible: {type(exc).__name__}") from exc
    try:
        return _parse_consolidated(book, physical)
    finally:
        book.close()


def _parse_consolidated(book, physical):
        layout, matched = _match_layout(book)

        sources = {role: Source(role, physical.name, physical.sha256, matched[role][0].title,
                                physical.has_links) for role in LAYOUTS[layout] if role in matched}
        scans = []
        attention = []
        ws, head = matched["Escaneo"]
        for number, row in enumerate(ws.iter_rows(min_row=head + 1), head + 1):
            if not any(text(cell.value) for cell in row):
                continue
            values, issues = [], []
            for column, label in ((1, "batch"), (4, "parte"), (6, "cantidad")):
                raw = row[column - 1].value if len(row) >= column else None
                values.append(raw)
                try:
                    _get(row, column, f"{ws.title} fila {number} {label}")
                except DataError:
                    issues.append(f"{label}: fórmula no verificable")
                if not text(raw):
                    issues.append(f"{label}: dato ausente")
            batch, part, qty = values
            try:
                key = scan_batch(batch) if text(batch) else ""
            except DataError as exc:
                key = ""
                if not any(issue.startswith("batch:") for issue in issues):
                    issues.append(f"batch: {exc}")
            try:
                normalized_part = part_key(part) if text(part) else ""
            except DataError as exc:
                normalized_part = ""
                if not any(issue.startswith("parte:") for issue in issues):
                    issues.append(f"parte: {exc}")
            try:
                quantity = positive_int(qty, f"{ws.title} fila {number} cantidad") if text(qty) else 0
            except DataError as exc:
                quantity = 0
                if not any(issue.startswith("cantidad:") for issue in issues):
                    issues.append(f"cantidad: {exc}")
            if issues:
                attention.append(AttentionRow(number, _raw(batch), _raw(part), _raw(qty),
                                              "; ".join(issues), sources["Escaneo"]))
                continue
            scans.append(Scan(number, text(batch), key, normalized_part, quantity,
                              sources["Escaneo"]))
        if not scans and not attention:
            raise DataError(f"{ws.title}: no hay partidas de escaneo")

        scan_keys = {(s.part, s.batch_key) for s in scans}
        china = []
        for role in (("China Free WK00", "China WK") if layout == "consolidado_4h_v1" else ("China",)):
            if role not in matched:
                continue
            columns = CHINA_COLUMNS[role]
            ws, head = matched[role]
            for number, row in enumerate(ws.iter_rows(min_row=head + 1), head + 1):
                if number == head + 1 and _secondary_china_header(row, columns):
                    continue
                part, batch = (_get(row, col, f"{ws.title} fila {number}") for col in columns[:2])
                if not text(part) or not text(batch):
                    continue
                try:
                    key = (part_key(part), china_batch(batch))
                except DataError:
                    continue
                if key not in scan_keys:
                    continue
                issues = []
                try:
                    qty = _get(row, columns[2], f"{ws.title} fila {number} cantidad")
                    quantity = positive_int(qty, f"{ws.title} fila {number} cantidad")
                except DataError as exc:
                    quantity = 0
                    issues.append(str(exc))
                try:
                    dn = _get(row, columns[3], f"{ws.title} fila {number} DN")
                    if not text(dn):
                        issues.append("DN vacío")
                except DataError as exc:
                    dn = ""
                    issues.append(str(exc))
                china.append(China(number, text(batch), key[1], key[0], quantity,
                                   text(dn), sources[role], "; ".join(issues)))

        refs = {(c.dn, c.part) for c in china if c.dn}
        transits = []
        ws, head = matched["Tránsitos"]
        for number, row in enumerate(ws.iter_rows(min_row=head + 1), head + 1):
            try:
                dn = _get(row, 14, f"{ws.title} fila {number} DN")
                part = _get(row, 18 if layout == "consolidado_4h_v1" else 19,
                            f"{ws.title} fila {number} parte")
                part = part_key(part)
            except DataError:
                continue
            if (text(dn), part) not in refs:
                continue
            issues, values = [], []
            for col, label in TRANSIT_COLUMNS[layout]:
                try:
                    values.append(optional_nonnegative_int(
                        _get(row, col, f"{ws.title} fila {number} {label}"),
                        f"{ws.title} fila {number} {label}"))
                except DataError as exc:
                    values.append(None)
                    issues.append(str(exc))
            qty, af, ag, ah = values
            status = "Por revisar"
            if layout == "consolidado_4h_v1" and not issues and all(value is not None for value in values):
                if af == ag == qty and ah == 0:
                    status = "Completo"
                elif af == ag == 0 and ah == qty:
                    status = "Pendiente"
            transits.append(Transit(number, text(dn), part, qty, ag, ah,
                                    sources["Tránsitos"], "; ".join(issues), af, status))
        return scans, china, transits, list(sources.values()), attention, layout
