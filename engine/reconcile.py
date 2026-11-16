"""Candidate generation; no DN is silently approved."""

from collections import defaultdict
from pathlib import Path
from data_models import Candidate, Item, Run
from normalize import DataError
from consolidated import read_consolidated, read_consolidated_bytes
from readers import read_china, read_scan, read_transit


def load_run(path: str, *args) -> Run:
    if len(args) in (2, 3):
        china_path, transit_path = args[:2]
        previous_hashes = args[2] if len(args) == 3 else None
        paths = [path, china_path, transit_path]
        if len({str(Path(p).resolve()).casefold() for p in paths}) != 3:
            raise DataError("El mismo archivo fue seleccionado dos veces en la corrida")
        scan_source, scans = read_scan(path)
        china_source, china = read_china(china_path, {(s.part, s.batch_key) for s in scans})
        transit_source, transits = read_transit(transit_path, {(c.dn, c.part) for c in china})
        sources = [scan_source, china_source, transit_source]
        legacy = True
        profile = "legacy_3source_v1"
    elif len(args) <= 1:
        previous_hashes = args[0] if args else None
        scans, china, transits, sources, attention, profile = read_consolidated(path)
        legacy = False
    else:
        raise TypeError("load_run requiere un consolidado o tres rutas históricas")
    return _finish_run(scans, china, transits, sources, attention if not legacy else [],
                       profile, previous_hashes)


def load_run_bytes(data: bytes) -> Run:
    """Apply the same reconciliation rules to an XLSX held entirely in memory."""
    scans, china, transits, sources, attention, profile = read_consolidated_bytes(data)
    return _finish_run(scans, china, transits, sources, attention, profile, None)


def _finish_run(scans, china, transits, sources, attention, profile, previous_hashes):
    legacy = profile == "legacy_3source_v1"
    run = Run(scans, china, transits, sources, attention=attention, profile=profile)
    if any(source.has_links for source in sources):
        run.warnings.append("Algún archivo contiene vínculos externos. No se abren ni actualizan; verifica los valores usados antes de confirmar.")
    if legacy:
        if previous_hashes and any(source.sha256 in previous_hashes for source in sources):
            run.warnings.append("Uno o más archivos son idénticos a una importación de esta sesión; confirma que no es una recarga accidental.")
    else:
        if previous_hashes and sources[0].sha256 in previous_hashes:
            run.warnings.append("Este consolidado es idéntico a una importación de esta sesión; confirma que no es una recarga accidental.")
        run.warnings.append("SHA-256 verifica solo el consolidado recibido; la procedencia y completitud de los libros previos a la copia manual no son verificables aquí.")
        if run.attention:
            run.warnings.append(f"Atención: {len(run.attention)} fila(s) sin conciliar. Corrige una copia del Excel y vuelve a cargarla.")
        if run.profile == "consolidado_3h_v1":
            run.warnings.append("En este formato, las cantidades de Tránsitos pueden depender de fórmulas; sus estados quedan Por revisar y solo DN (N) confirma el cruce.")
        elif run.profile == "consolidado_4h_v1" and not any(
            c.source.kind == "China WK" for c in run.china
        ):
            run.warnings.append("China WK no aportó partidas; se analizaron Escaneo, China Free WK00 y Tránsitos.")
    propose(run)
    return run


def propose(run: Run) -> None:
    china_by_key = defaultdict(list)
    for row in run.china:
        china_by_key[(row.part, row.batch_key)].append(row)
    transit_by_key = defaultdict(list)
    for row in run.transits:
        transit_by_key[(row.part, row.dn)].append(row)
    result = []
    for scan in run.scans:
        if scan.issue:
            result.append(Item(scan, state="por_revisar", reason=scan.issue))
            continue
        matches = china_by_key[(scan.part, scan.batch_key)]
        if not matches:
            result.append(Item(scan, state="sin_cruce", reason="Sin parte y batch correspondientes en China"))
            continue
        candidates = []
        for china in matches:
            issues = []
            if china.issue:
                issues.append(china.issue)
            transits = transit_by_key[(scan.part, china.dn)]
            transit = transits[0] if len(transits) == 1 else None
            if len(transits) > 1:
                issues.append("Varias filas en tránsitos: revisar contexto")
            elif len(transits) == 0:
                issues.append("DN no encontrado en tránsitos")
            elif transit.issue:
                issues.append(transit.issue)
            elif run.profile != "legacy_3source_v1" and transit.status == "Por revisar":
                issues.append("Tránsito por revisar")
            candidates.append(Candidate(china, transit, "; ".join(issues)))
        unique = {(c.china.dn, c.china.raw_batch) for c in candidates}
        if len(unique) > 1:
            state = "ambiguo"
            reason = "Varios DN o batches completos comparten la clave corta; supervisor debe confirmar reparto"
        elif any(c.issue for c in candidates):
            state = "por_revisar"
            reason = "; ".join(c.issue for c in candidates if c.issue)
        else:
            state = "propuesto"
            reason = "Cruce propuesto; requiere confirmación del supervisor"
        result.append(Item(scan, candidates, state, reason))
    run.items = result
