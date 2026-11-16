"""Conservative identifiers: malformed values remain exceptions."""

import re


class DataError(ValueError):
    pass


def validate_excel_text(value: str, label: str) -> str:
    """Reject XML 1.0 invalid code points before openpyxl sees any text."""
    for character in value:
        code = ord(character)
        if not (code in (0x09, 0x0A, 0x0D) or
                0x20 <= code <= 0xD7FF or
                0xE000 <= code <= 0xFFFD or
                0x10000 <= code <= 0x10FFFF):
            raise DataError(f"{label}: contiene caracteres incompatibles con Excel")
    return value


def text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def part_key(value: object) -> str:
    raw = text(value).upper()
    if not raw:
        raise DataError("Número de parte vacío")
    # China omits the leading K for white-line parts; T is kept for TV.
    return raw[1:] if re.fullmatch(r"K[0-9A-Z]+", raw) else raw


def scan_batch(value: object) -> str:
    raw = text(value).upper()
    if len(raw) < 13:
        raise DataError("BATCH escaneado demasiado corto para posición 9 + 5")
    segment = raw[8:13]
    if not re.fullmatch(r"[A-Z][0-9A-Z]{4}", segment):
        raise DataError("BATCH escaneado sin letra y cuatro caracteres en posición 9")
    return segment[0] + "-" + segment[1:]


def china_batch(value: object) -> str:
    raw = text(value).upper().replace("-", "")
    if len(raw) < 5 or not re.fullmatch(r"[A-Z][0-9A-Z]{4,}", raw):
        raise DataError("BATCH China sin letra y cuatro caracteres")
    return raw[0] + "-" + raw[1:5]


def positive_int(value: object, label: str) -> int:
    raw = text(value)
    try:
        number = float(raw)
    except ValueError as exc:
        raise DataError(f"{label}: cantidad no numérica") from exc
    if not number.is_integer() or number <= 0 or number > 1_000_000_000:
        raise DataError(f"{label}: se requiere entero positivo")
    return int(number)


def optional_nonnegative_int(value: object, label: str) -> int | None:
    if text(value) == "":
        return None
    raw = text(value)
    try:
        number = float(raw)
    except ValueError as exc:
        raise DataError(f"{label}: cantidad no numérica") from exc
    if not number.is_integer() or number < 0 or number > 1_000_000_000:
        raise DataError(f"{label}: se requiere entero no negativo")
    return int(number)
