"""Supervisor allocations are explicit, bounded and reversible in memory."""

from data_models import Decision, Run
from normalize import DataError, validate_excel_text


def assign(run: Run, scan_row: int, *args) -> Decision:
    if len(args) == 4:
        china_sheet, china_row, quantity, reason = args
    elif len(args) == 3:
        china_row, quantity, reason = args
        sheets = {c.china.source.sheet for item in run.items if item.scan.row == scan_row
                  for c in item.candidates if c.china.row == china_row}
        if len(sheets) != 1:
            raise DataError("Indica hoja China para identificar la línea sin ambigüedad")
        china_sheet = sheets.pop()
    else:
        raise TypeError("assign requiere hoja, fila, cantidad y motivo")
    item = next((item for item in run.items if item.scan.row == scan_row), None)
    if item is None:
        raise DataError("Partida escaneada desconocida")
    candidate = next((candidate for candidate in item.candidates if
                      candidate.china.row == china_row and candidate.china.source.sheet == china_sheet), None)
    if candidate is None:
        raise DataError("DN candidato desconocido para esta partida")
    if candidate.china.issue:
        raise DataError("Candidato con DN o cantidad no verificable; no se puede asignar")
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        raise DataError("Cantidad de reparto debe ser entero positivo")
    if not isinstance(reason, str):
        raise DataError("Motivo inválido")
    validate_excel_text(reason, "Motivo")
    if not reason.strip() or len(reason.strip()) > 500:
        raise DataError("Registra un motivo de 1 a 500 caracteres")
    existing = [d for d in run.decisions if d.scan_row == scan_row]
    if any(d.china_row == china_row and d.china_sheet == china_sheet for d in existing):
        raise DataError("Este DN ya tiene un reparto en la partida; elimina primero el anterior")
    if sum(d.quantity for d in existing) + quantity > item.scan.quantity:
        raise DataError("El reparto excede la cantidad escaneada")
    # The same China line can be proposed to several scan rows. A per-row
    # check would silently overbook the expected quantity.
    lookup = {(row.scan.row, option.china.source.sheet, option.china.row): option
              for row in run.items for option in row.candidates}
    china_identity = (candidate.china.source.sha256, china_sheet, candidate.china.row)
    used_china = 0
    for decision in run.decisions:
        previous = lookup.get((decision.scan_row, decision.china_sheet, decision.china_row))
        if previous is None:
            raise DataError("Existe una decisión sin candidato verificable; revisa la corrida")
        if (previous.china.source.sha256, previous.china.source.sheet, previous.china.row) == china_identity:
            used_china += decision.quantity
    if used_china + quantity > candidate.china.quantity:
        raise DataError("El reparto acumulado excede la cantidad esperada por este DN en China")
    decision = Decision(scan_row, candidate.china.dn, china_row, quantity, reason.strip(), china_sheet)
    run.decisions.append(decision)
    return decision


def remove(run: Run, scan_row: int, *args) -> None:
    if len(args) == 2:
        china_sheet, china_row = args
    elif len(args) == 1:
        china_row = args[0]
        sheets = {d.china_sheet for d in run.decisions if d.scan_row == scan_row and d.china_row == china_row}
        if len(sheets) != 1:
            raise DataError("Indica hoja China para retirar la línea sin ambigüedad")
        china_sheet = sheets.pop()
    else:
        raise TypeError("remove requiere hoja y fila China")
    run.decisions = [decision for decision in run.decisions
                     if not (decision.scan_row == scan_row and decision.china_sheet == china_sheet
                             and decision.china_row == china_row)]
