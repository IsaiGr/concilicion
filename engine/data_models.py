"""Typed, source-aware records for the local reconciliation workflow."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Source:
    kind: str
    name: str
    sha256: str
    sheet: str
    has_links: bool = False


@dataclass(frozen=True)
class Scan:
    row: int
    raw_batch: str
    batch_key: str
    part: str
    quantity: int
    source: Source
    issue: str = ""


@dataclass(frozen=True)
class AttentionRow:
    row: int
    raw_batch: str
    raw_part: str
    raw_quantity: str
    reason: str
    source: Source


@dataclass(frozen=True)
class China:
    row: int
    raw_batch: str
    batch_key: str
    part: str
    quantity: int
    dn: str
    source: Source
    issue: str = ""


@dataclass(frozen=True)
class Transit:
    row: int
    dn: str
    part: str
    expected: int | None
    received: int | None
    not_received: int | None
    source: Source
    issue: str = ""
    received_af: int | None = None
    status: str = "Por revisar"


@dataclass(frozen=True)
class Candidate:
    china: China
    transit: Transit | None
    issue: str


@dataclass
class Item:
    scan: Scan
    candidates: list[Candidate] = field(default_factory=list)
    state: str = "pendiente"
    reason: str = ""


@dataclass(frozen=True)
class Decision:
    scan_row: int
    dn: str
    china_row: int
    quantity: int
    reason: str
    china_sheet: str = ""


@dataclass
class Run:
    scans: list[Scan]
    china: list[China]
    transits: list[Transit]
    sources: list[Source]
    items: list[Item] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    attention: list[AttentionRow] = field(default_factory=list)
    profile: str = "legacy_3source_v1"
