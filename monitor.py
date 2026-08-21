#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ISO NOWOŚCI - monitor nowości w bazie norm ISO.

Pobiera plik CSV z ISO Open Data, porównuje go z poprzednim pobraniem
i wysyła na Discord powiadomienia o wykrytych zmianach:

    NEW        nowa norma / nowa pozycja w bazie
    REVISION   rewizja, nowe wydanie
    WITHDRAWN  wycofanie normy
    STAGE      zmiana etapu DIS / FDIS

Stan poprzedniego pobrania jest zapisywany w katalogu ./state
(lekki snapshot CSV + metadane ETag), dzięki czemu kolejny przebieg
wie dokładnie, co się zmieniło.

Uruchomienie:
    python monitor.py                 # normalny przebieg
    python monitor.py --dry-run       # bez wysyłki na Discord
    python monitor.py --baseline      # tylko zapis stanu, bez powiadomień
    python monitor.py --csv plik.csv  # praca na lokalnym pliku CSV
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import requests

# --------------------------------------------------------------------------
# Stale
# --------------------------------------------------------------------------

CSV_URL = os.getenv(
    "ISO_CSV_URL",
    "https://isopublicstorageprod.blob.core.windows.net/opendata/"
    "_latest/iso_deliverables_metadata/csv/iso_deliverables_metadata.csv",
)

STANDARD_URL = "https://www.iso.org/standard/{id}.html"

SNAPSHOT_HEADER = ["id", "reference", "currentStage", "edition", "publicationDate"]
EXPECTED_CSV_START = "id,deliverableType"

APP_NAME = "ISO Nowości"
USER_AGENT = "iso-nowosci-monitor/1.0"

DASH = "—"          # em dash
ARROW = "→"         # ->
DOWN = "↓"          # v
BULLET = "•"        # *

# Rodzaje zmian: ikona, opis, kolor embeda, priorytet wysyłki
KINDS: Dict[str, dict] = {
    "NEW":       {"icon": "\U0001F195", "label": "Nowa norma",             "color": 0x2ECC71, "prio": 0},
    "REVISION":  {"icon": "\U0001F504", "label": "Rewizja / nowe wydanie", "color": 0x3498DB, "prio": 1},
    "WITHDRAWN": {"icon": "⛔",     "label": "Wycofanie normy",        "color": 0xE74C3C, "prio": 2},
    "STAGE":     {"icon": "⏳",     "label": "Zmiana etapu DIS/FDIS",  "color": 0xF39C12, "prio": 3},
    "INFO":      {"icon": "ℹ",     "label": "Informacja",             "color": 0x95A5A6, "prio": 9},
}

# Kody etapów ISO (Harmonized Stage Codes).
# W CSV zapisane bez kropki i bez wiodących zer, np. 9599 = 95.99, 98 = 00.98
STAGE_NAMES: Dict[str, str] = {
    "00.00": "Propozycja nowego projektu otrzymana",
    "00.20": "Propozycja nowego projektu w przeglądzie",
    "00.60": "Zakończenie przeglądu",
    "00.98": "Propozycja nowego projektu zaniechana",
    "00.99": "Zgoda na głosowanie nad propozycją nowego projektu",
    "10.00": "Propozycja nowego projektu zarejestrowana",
    "10.20": "Rozpoczęto głosowanie nad nowym projektem (NP)",
    "10.60": "Zakończenie głosowania",
    "10.92": "Propozycja zwrócona do wnioskodawcy",
    "10.98": "Nowy projekt odrzucony",
    "10.99": "Nowy projekt zatwierdzony",
    "20.00": "Nowy projekt w programie prac komitetu",
    "20.20": "Rozpoczęto prace nad projektem roboczym (WD)",
    "20.60": "Zakończenie zgłaszania uwag",
    "20.98": "Projekt usunięty",
    "20.99": "WD zatwierdzony do rejestracji jako CD",
    "30.00": "Projekt komitetu (CD) zarejestrowany",
    "30.20": "Rozpoczęto analizę / głosowanie nad CD",
    "30.60": "Zakończenie głosowania nad CD",
    "30.92": "CD skierowany z powrotem do grupy roboczej",
    "30.98": "Projekt usunięty",
    "30.99": "CD zatwierdzony do rejestracji jako DIS",
    "40.00": "DIS zarejestrowany",
    "40.20": "Rozpoczęto głosowanie nad DIS (12 tygodni)",
    "40.60": "Zakończenie głosowania nad DIS",
    "40.92": "DIS skierowany z powrotem do komitetu",
    "40.93": "Decyzja o ponownym głosowaniu nad DIS",
    "40.98": "Projekt usunięty",
    "40.99": "DIS zatwierdzony do rejestracji jako FDIS",
    "50.00": "FDIS zarejestrowany do formalnego zatwierdzenia",
    "50.20": "Rozpoczęto głosowanie nad FDIS (8 tygodni)",
    "50.60": "Zakończenie głosowania nad FDIS",
    "50.92": "FDIS skierowany z powrotem do komitetu",
    "50.98": "Projekt usunięty",
    "50.99": "FDIS zatwierdzony do publikacji",
    "60.00": "Norma w trakcie publikacji",
    "60.60": "Norma Międzynarodowa opublikowana",
    "90.20": "Norma w przeglądzie systematycznym",
    "90.60": "Zakończenie przeglądu",
    "90.92": "Norma do zrewidowania",
    "90.93": "Norma potwierdzona",
    "90.99": "Wniosek o wycofanie normy",
    "95.20": "Rozpoczęto głosowanie nad wycofaniem",
    "95.60": "Zakończenie głosowania nad wycofaniem",
    "95.92": "Decyzja o niewycofywaniu normy",
    "95.99": "Norma wycofana",
}

MAIN_STAGES = {
    "00": "Etap wstępny", "10": "Etap propozycji", "20": "Etap przygotowawczy",
    "30": "Etap komitetu", "40": "Etap ankiety (DIS)", "50": "Etap zatwierdzenia (FDIS)",
    "60": "Etap publikacji", "90": "Etap przeglądu", "95": "Etap wycofania",
}

SUBSTAGES = {
    "00": "rejestracja", "20": "rozpoczęcie działania", "60": "zakończenie działania",
    "90": "decyzja", "92": "powtórzenie poprzedniej fazy", "93": "powtórzenie bieżącej fazy",
    "98": "zaniechanie", "99": "kontynuacja",
}

DELIVERABLE_TYPES = {
    "IS": "Norma Międzynarodowa (IS)", "TS": "Specyfikacja Techniczna (TS)",
    "TR": "Raport Techniczny (TR)", "PAS": "Publicznie Dostępna Specyfikacja (PAS)",
    "GUIDE": "Przewodnik ISO", "IWA": "Porozumienie Warsztatowe (IWA)",
    "R": "Zalecenie ISO (R)", "ISP": "Profil Standaryzowany (ISP)",
    "DATA": "Zestaw danych", "TTA": "Umowa Technologiczna (TTA)",
}


# --------------------------------------------------------------------------
# Pomocnicze
# --------------------------------------------------------------------------


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def env_flag(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "y", "on", "tak")


def env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    try:
        return int(raw)
    except ValueError:
        return default


def env_list(name: str) -> List[str]:
    raw = (os.getenv(name) or "").strip()
    return [part.strip() for part in raw.split(",") if part.strip()]


def raise_csv_field_limit() -> None:
    """Kolumna scope.en bywa bardzo długa - podnosimy limit pola CSV."""
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 2


def trim(text: str, length: int) -> str:
    """Skleja białe znaki i przycina do zadanej długości."""
    text = " ".join((text or "").split())
    return text if len(text) <= length else text[: length - 1].rstrip() + "…"


def norm_stage(raw: str) -> str:
    """'9599' -> '9599', '98' -> '0098', śmieć -> ''."""
    value = (raw or "").strip()
    return value.zfill(4) if value.isdigit() and len(value) <= 4 else ""


def stage_dotted(code: str) -> str:
    return f"{code[:2]}.{code[2:]}" if len(code) == 4 else "?"


def stage_label(code: str) -> str:
    if not code:
        return "brak danych"
    dotted = stage_dotted(code)
    if dotted in STAGE_NAMES:
        return STAGE_NAMES[dotted]
    main = MAIN_STAGES.get(code[:2], f"etap {code[:2]}")
    sub = SUBSTAGES.get(code[2:], f"podetap {code[2:]}")
    return f"{main} - {sub}"


def stage_text(code: str) -> str:
    return f"`{stage_dotted(code)}` {stage_label(code)}" if code else DASH


def is_deleted_stage(code: str) -> bool:
    """Podetap .98 oznacza projekt zaniechany / usunięty."""
    return len(code) == 4 and code[2:] == "98"


def edition_num(raw: str) -> int:
    match = re.search(r"\d+", raw or "")
    return int(match.group()) if match else 0


def parse_id_list(raw: str) -> List[str]:
    """Kolumny replaces / replacedBy mają postać "[12345]" lub "[1, 2]"."""
    return re.findall(r"\d+", raw or "")


def id_sort_key(sid: str) -> Tuple[int, object]:
    return (0, int(sid)) if sid.isdigit() else (1, sid)


def fmt_id_links(ids: Sequence[str], limit: int = 3) -> str:
    parts = [f"[{i}]({STANDARD_URL.format(id=i)})" for i in ids[:limit]]
    if len(ids) > limit:
        parts.append(f"+{len(ids) - limit}")
    return ", ".join(parts)


# --------------------------------------------------------------------------
# Konfiguracja
# --------------------------------------------------------------------------


@dataclass
class Config:
    webhook: str
    state_dir: Path
    data_dir: Path
    dry_run: bool
    baseline: bool
    force: bool
    max_messages: int
    watch_prefixes: List[str]
    notify_all_stages: bool
    ignore_deleted: bool
    committees: List[str]
    types: List[str]
    keywords: List[str]
    icon_url: str
    username: str

    @property
    def snapshot_path(self) -> Path:
        return self.state_dir / "iso_snapshot.csv"

    @property
    def meta_path(self) -> Path:
        return self.state_dir / "meta.json"

    @property
    def csv_path(self) -> Path:
        return self.data_dir / "iso_deliverables_metadata.csv"


def resolve_icon_url() -> str:
    """Ikona aplikacji (ikona.png) służy jako avatar webhooka Discord."""
    explicit = (os.getenv("ICON_URL") or "").strip()
    if explicit:
        return explicit
    repo = (os.getenv("GITHUB_REPOSITORY") or "").strip()
    if repo:
        branch = (os.getenv("GITHUB_REF_NAME") or "main").strip() or "main"
        return f"https://raw.githubusercontent.com/{repo}/{branch}/ikona.png"
    return ""


def build_config(args: argparse.Namespace) -> Config:
    root = Path(__file__).resolve().parent
    watch_raw = (os.getenv("STAGE_WATCH_PREFIXES") or "40,50")
    return Config(
        webhook=(os.getenv("DISCORD_WEBHOOK_URL") or "").strip(),
        state_dir=Path(args.state_dir) if args.state_dir else root / "state",
        data_dir=Path(args.data_dir) if args.data_dir else root / "data",
        dry_run=args.dry_run,
        baseline=args.baseline,
        force=args.force,
        max_messages=args.limit if args.limit is not None else env_int("MAX_MESSAGES", 250),
        watch_prefixes=[p.strip() for p in watch_raw.split(",") if p.strip()],
        notify_all_stages=env_flag("NOTIFY_ALL_STAGE_CHANGES", False),
        ignore_deleted=env_flag("IGNORE_DELETED_PROJECTS", True),
        committees=[c.upper() for c in env_list("FILTER_COMMITTEES")],
        types=[t.upper() for t in env_list("FILTER_TYPES")],
        keywords=[k.lower() for k in env_list("FILTER_KEYWORDS")],
        icon_url=resolve_icon_url(),
        username=(os.getenv("DISCORD_USERNAME") or APP_NAME).strip(),
    )


# --------------------------------------------------------------------------
# Model zmiany
# --------------------------------------------------------------------------


@dataclass
class Change:
    kind: str
    sid: str
    reference: str
    title: str = ""
    pub_date: str = ""
    committee: str = ""
    dtype: str = ""
    edition: str = ""
    old_stage: str = ""
    new_stage: str = ""
    note: str = ""

    @property
    def url(self) -> str:
        return STANDARD_URL.format(id=self.sid)


# --------------------------------------------------------------------------
# Stan (snapshot poprzedniego pobrania)
# --------------------------------------------------------------------------

Record = Tuple[str, str, str, str]      # reference, stage, edition, publicationDate


def load_snapshot(path: Path) -> Dict[str, Record]:
    data: Dict[str, Record] = {}
    if not path.exists():
        return data
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header and header[0] != "id":        # brak nagłówka - to już rekord
            handle.seek(0)
            reader = csv.reader(handle)
        for row in reader:
            if len(row) >= 5 and row[0]:
                data[row[0]] = (row[1], row[2], row[3], row[4])
    return data


def save_snapshot(path: Path, records: Dict[str, Record]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(SNAPSHOT_HEADER)
        for sid in sorted(records, key=id_sort_key):
            writer.writerow([sid, *records[sid]])
    tmp.replace(path)


def load_meta(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        log("OSTRZEŻENIE: nie udało się odczytać meta.json - zaczynam od zera")
        return {}


def save_meta(path: Path, meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


# --------------------------------------------------------------------------
# Pobieranie CSV
# --------------------------------------------------------------------------


def download_csv(dest: Path, meta: dict, force: bool, attempts: int = 3,
                 progress=None) -> Tuple[str, dict]:
    """Zwraca ('unchanged', {}) albo ('ok', {etag, last_modified, bytes}).

    progress: opcjonalna funkcja progress(pobrano_bajtow, wszystkich_bajtow)
              wywoływana w trakcie pobierania (używa jej aplikacja okienkowa).
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": USER_AGENT}
    if not force and meta.get("etag"):
        headers["If-None-Match"] = meta["etag"]

    last_error: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            log(f"Pobieram CSV z ISO Open Data (próba {attempt}/{attempts})...")
            with requests.get(CSV_URL, headers=headers, stream=True, timeout=(30, 300)) as resp:
                if resp.status_code == 304:
                    return "unchanged", {}
                resp.raise_for_status()

                expected = int(resp.headers.get("Content-Length") or 0)
                tmp = dest.with_suffix(".part")
                total = 0
                with tmp.open("wb") as handle:
                    for chunk in resp.iter_content(chunk_size=1 << 20):
                        if chunk:
                            handle.write(chunk)
                            total += len(chunk)
                            if progress is not None:
                                progress(total, expected)

                if total < 1_000_000:
                    tmp.unlink(missing_ok=True)
                    raise RuntimeError(f"plik podejrzanie mały ({total} B)")

                with tmp.open("r", encoding="utf-8-sig", errors="replace") as handle:
                    first_line = handle.readline()
                if not first_line.startswith(EXPECTED_CSV_START):
                    tmp.unlink(missing_ok=True)
                    raise RuntimeError(f"nieoczekiwany nagłówek CSV: {first_line[:80]!r}")

                tmp.replace(dest)
                log(f"Pobrano {total / 1024 / 1024:.1f} MB")
                return "ok", {
                    "etag": resp.headers.get("ETag", ""),
                    "last_modified": resp.headers.get("Last-Modified", ""),
                    "bytes": total,
                }
        except Exception as exc:                                    # noqa: BLE001
            last_error = exc
            log(f"Błąd pobierania: {exc}")
            if attempt < attempts:
                time.sleep(5 * attempt)

    raise RuntimeError(f"Nie udało się pobrać CSV po {attempts} próbach: {last_error}")


# --------------------------------------------------------------------------
# Wykrywanie zmian
# --------------------------------------------------------------------------


def stage_note(new_stage: str) -> str:
    return {
        "40": "Projekt jest w fazie **DIS** (ankieta publiczna)",
        "50": "Projekt jest w fazie **FDIS** (końcowe zatwierdzenie)",
        "60": "Projekt jest w fazie **publikacji**",
    }.get(new_stage[:2], "")


def classify(sid: str, old: Optional[Record], row: Dict[str, str], cfg: Config) -> Optional[Change]:
    """Zwraca co najwyżej jedno - najistotniejsze - zdarzenie dla danej pozycji."""
    new_stage = norm_stage(row.get("currentStage", ""))
    reference = (row.get("reference") or "").strip()
    edition = (row.get("edition") or "").strip()
    pub_date = (row.get("publicationDate") or "").strip()
    replaces = parse_id_list(row.get("replaces", ""))

    def make(kind: str, note: str = "", old_stage: str = "") -> Change:
        return Change(
            kind=kind,
            sid=sid,
            reference=reference or f"ISO id {sid}",
            title=(row.get("title.en") or "").strip() or (row.get("title.fr") or "").strip(),
            pub_date=pub_date,
            committee=(row.get("ownerCommittee") or "").strip(),
            dtype=(row.get("deliverableType") or "").strip(),
            edition=edition,
            old_stage=old_stage,
            new_stage=new_stage,
            note=note,
        )

    # --- pozycja, której wcześniej nie było w bazie ------------------------
    if old is None:
        if is_deleted_stage(new_stage) or new_stage.startswith("95"):
            return None                     # wpis historyczny, od razu martwy
        if replaces:
            return make("REVISION", f"Nowy projekt zastępujący: {fmt_id_links(replaces)}")
        return make("NEW", "Nowa pozycja w bazie ISO")

    old_ref, old_stage, old_edition, old_pub = old

    # --- zmiana etapu ------------------------------------------------------
    if new_stage and new_stage != old_stage:
        if new_stage.startswith("95") and not old_stage.startswith("95"):
            return make("WITHDRAWN", "Norma została wycofana", old_stage)

        if new_stage == "6060" and old_stage != "6060":
            if edition_num(edition) > 1 or replaces:
                note = "Opublikowano nowe wydanie normy"
                if replaces:
                    note += f" (zastępuje: {fmt_id_links(replaces)})"
                return make("REVISION", note, old_stage)
            return make("NEW", "Norma została opublikowana", old_stage)

        if is_deleted_stage(new_stage) and cfg.ignore_deleted:
            return None

        if new_stage[:2] in cfg.watch_prefixes or cfg.notify_all_stages:
            return make("STAGE", stage_note(new_stage), old_stage)
        return None

    # --- etap bez zmian, ale zmieniły się dane wydania ---------------------
    if edition and edition != old_edition and edition_num(edition) > edition_num(old_edition):
        previous = old_edition or DASH
        return make("REVISION", f"Zmiana wydania: {previous} {ARROW} {edition}", old_stage)

    if pub_date and pub_date != old_pub:
        if old_pub:
            return make("REVISION", f"Zmiana daty publikacji: {old_pub} {ARROW} {pub_date}", old_stage)
        kind = "REVISION" if edition_num(edition) > 1 else "NEW"
        return make(kind, "Nadano datę publikacji", old_stage)

    if cfg.notify_all_stages and reference and reference != old_ref:
        return make("STAGE", f"Zmiana oznaczenia: {old_ref} {ARROW} {reference}", old_stage)

    return None


def scan_csv(path: Path, prev: Dict[str, Record], cfg: Config,
             baseline: bool) -> Tuple[Dict[str, Record], List[Change]]:
    """Strumieniowo czyta CSV, buduje nowy snapshot i listę zmian."""
    current: Dict[str, Record] = {}
    changes: List[Change] = []

    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = {"id", "reference", "currentStage"} - set(reader.fieldnames or [])
        if missing:
            raise RuntimeError(f"CSV nie zawiera wymaganych kolumn: {sorted(missing)}")

        for row in reader:
            sid = (row.get("id") or "").strip()
            if not sid:
                continue
            current[sid] = (
                (row.get("reference") or "").strip(),
                norm_stage(row.get("currentStage", "")),
                (row.get("edition") or "").strip(),
                (row.get("publicationDate") or "").strip(),
            )
            if baseline:
                continue
            change = classify(sid, prev.get(sid), row, cfg)
            if change is not None:
                changes.append(change)

    if not baseline:
        for sid, old in prev.items():
            if sid in current:
                continue
            old_ref, old_stage, old_edition, old_pub = old
            changes.append(Change(
                kind="WITHDRAWN", sid=sid, reference=old_ref or f"ISO id {sid}",
                pub_date=old_pub, edition=old_edition, old_stage=old_stage,
                note="Pozycja zniknęła z bazy ISO Open Data",
            ))

    return current, changes


def apply_filters(changes: List[Change], cfg: Config) -> List[Change]:
    if not (cfg.committees or cfg.types or cfg.keywords):
        return changes
    kept: List[Change] = []
    for change in changes:
        if cfg.committees:
            committee = change.committee.upper()
            if not any(committee.startswith(prefix) for prefix in cfg.committees):
                continue
        if cfg.types and change.dtype.upper() not in cfg.types:
            continue
        if cfg.keywords:
            haystack = f"{change.title} {change.reference}".lower()
            if not any(keyword in haystack for keyword in cfg.keywords):
                continue
        kept.append(change)
    return kept


# --------------------------------------------------------------------------
# Discord
# --------------------------------------------------------------------------


def build_embed(change: Change, cfg: Config) -> dict:
    kind = KINDS[change.kind]

    description: List[str] = []
    if change.title:
        description.append(f"**{trim(change.title, 800)}**")
    if change.note:
        description.append(change.note)
    description.append(f"[\U0001F517 Zobacz na iso.org]({change.url})")

    if change.old_stage and change.new_stage and change.old_stage != change.new_stage:
        stage_value = f"{stage_text(change.old_stage)}\n{DOWN}\n{stage_text(change.new_stage)}"
    else:
        stage_value = stage_text(change.new_stage or change.old_stage)

    footer_parts = [kind["label"],
                    DELIVERABLE_TYPES.get(change.dtype.upper(), change.dtype or DASH)]
    if change.edition:
        footer_parts.append(f"wydanie {change.edition}")
    footer_parts.append(f"id {change.sid}")

    embed = {
        "title": trim(f"{kind['icon']} {change.reference}", 250),
        "url": change.url,
        "description": "\n".join(description)[:4000],
        "color": kind["color"],
        "fields": [
            {"name": "\U0001F4C5 Data publikacji",
             "value": change.pub_date or f"{DASH} (jeszcze nieopublikowana)", "inline": True},
            {"name": "\U0001F3DB Komitet techniczny",
             "value": change.committee or DASH, "inline": True},
            {"name": "\U0001F4CA Etap", "value": stage_value[:1000], "inline": False},
        ],
        "footer": {"text": trim(f" {BULLET} ".join(footer_parts), 2000)},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if cfg.icon_url:
        embed["footer"]["icon_url"] = cfg.icon_url
    return embed


def build_info_embed(title: str, text: str, cfg: Config) -> dict:
    embed = {
        "title": trim(title, 250),
        "description": text[:4000],
        "color": KINDS["INFO"]["color"],
        "footer": {"text": APP_NAME},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if cfg.icon_url:
        embed["footer"]["icon_url"] = cfg.icon_url
    return embed


class DiscordSender:
    """Wysyłka na webhook. Discord przyjmuje max 10 embedów na wiadomość."""

    BATCH = 10

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.sent = 0
        self.failed = 0

    def _payload(self, embeds: List[dict], content: Optional[str]) -> dict:
        payload: dict = {"embeds": embeds, "allowed_mentions": {"parse": []}}
        if self.cfg.username:
            payload["username"] = self.cfg.username
        if self.cfg.icon_url:
            payload["avatar_url"] = self.cfg.icon_url
        if content:
            payload["content"] = content[:1900]
        return payload

    def _post(self, payload: dict, attempts: int = 5) -> bool:
        url = self.cfg.webhook
        url += ("&" if "?" in url else "?") + "wait=true"

        for attempt in range(1, attempts + 1):
            try:
                resp = self.session.post(url, json=payload, timeout=30)
            except requests.RequestException as exc:
                log(f"Błąd sieci przy wysyłce na Discord: {exc}")
                time.sleep(3 * attempt)
                continue

            if resp.status_code in (200, 204):
                return True

            if resp.status_code == 429:
                try:
                    retry_after = float(resp.json().get("retry_after", 2))
                except (ValueError, AttributeError, TypeError):
                    retry_after = 2.0
                log(f"Discord rate limit - czekam {retry_after:.1f}s")
                time.sleep(min(retry_after + 0.5, 60))
                continue

            if resp.status_code in (401, 403, 404):
                log(f"BŁĄD: webhook odrzucony (HTTP {resp.status_code}). "
                    f"Sprawdź sekret DISCORD_WEBHOOK_URL. Odpowiedź: {resp.text[:200]}")
                return False

            if 500 <= resp.status_code < 600:
                log(f"Discord HTTP {resp.status_code} - ponawiam...")
                time.sleep(3 * attempt)
                continue

            log(f"BŁĄD Discord HTTP {resp.status_code}: {resp.text[:300]}")
            return False

        log("BŁĄD: wyczerpano próby wysyłki na Discord.")
        return False

    def send_embeds(self, embeds: List[dict], content: Optional[str] = None) -> bool:
        all_ok = True
        for index in range(0, len(embeds), self.BATCH):
            batch = embeds[index:index + self.BATCH]
            head = content if index == 0 else None
            if self.cfg.dry_run:
                self.sent += len(batch)
                continue
            if self._post(self._payload(batch, head)):
                self.sent += len(batch)
            else:
                self.failed += len(batch)
                all_ok = False
            time.sleep(0.7)             # limit webhooka to ok. 5 żądań / 2 s
        return all_ok


# --------------------------------------------------------------------------
# Raportowanie
# --------------------------------------------------------------------------


def counts_by_kind(changes: List[Change]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for change in changes:
        counts[change.kind] = counts.get(change.kind, 0) + 1
    return counts


def summary_line(changes: List[Change]) -> str:
    counts = counts_by_kind(changes)
    parts = [f"{KINDS[kind]['icon']} {KINDS[kind]['label']}: **{counts[kind]}**"
             for kind in ("NEW", "REVISION", "WITHDRAWN", "STAGE") if counts.get(kind)]
    return f" {BULLET} ".join(parts) if parts else "brak zmian"


def write_job_summary(text: str) -> None:
    path = os.getenv("GITHUB_STEP_SUMMARY")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    except OSError:
        pass


def print_changes(changes: List[Change], limit: int = 60) -> None:
    for change in changes[:limit]:
        old = stage_dotted(change.old_stage) if change.old_stage else "--"
        new = stage_dotted(change.new_stage) if change.new_stage else "--"
        log(f"  [{change.kind:9}] {change.reference:<34} {old:>5} -> {new:<5} "
            f"| {trim(change.title, 70)}")
    if len(changes) > limit:
        log(f"  ... oraz {len(changes) - limit} kolejnych")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor nowości w bazie norm ISO -> Discord")
    parser.add_argument("--dry-run", action="store_true",
                        help="nie wysyłaj na Discord i nie zapisuj stanu")
    parser.add_argument("--baseline", action="store_true",
                        help="zapisz stan początkowy bez wysyłania powiadomień")
    parser.add_argument("--force", action="store_true",
                        help="pobierz CSV ignorując zapisany ETag")
    parser.add_argument("--csv", dest="csv_file", default=None,
                        help="użyj lokalnego pliku CSV zamiast pobierania")
    parser.add_argument("--limit", type=int, default=None,
                        help="maksymalna liczba powiadomień w jednym przebiegu")
    parser.add_argument("--state-dir", default=None, help="katalog stanu (domyślnie ./state)")
    parser.add_argument("--data-dir", default=None, help="katalog na pobrany CSV (domyślnie ./data)")
    parser.add_argument("--save-state", action="store_true",
                        help="zapisz stan mimo --dry-run")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[attr-defined]
    except Exception:                                                # noqa: BLE001
        pass

    raise_csv_field_limit()
    args = parse_args(argv)
    cfg = build_config(args)

    if not cfg.webhook and not (cfg.dry_run or cfg.baseline):
        log("BŁĄD: brak zmiennej środowiskowej DISCORD_WEBHOOK_URL.")
        log("      Ustaw ją jako GitHub Secret albo uruchom z --dry-run.")
        return 2

    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)

    meta = load_meta(cfg.meta_path)
    prev = load_snapshot(cfg.snapshot_path)
    baseline = cfg.baseline or not prev
    if baseline and not cfg.baseline:
        log("Brak zapisanego stanu - ten przebieg tworzy stan bazowy (bez powiadomień).")

    # --- zrodlo danych -----------------------------------------------------
    download_info: dict = {}
    if args.csv_file:
        csv_path = Path(args.csv_file)
        if not csv_path.exists():
            log(f"BŁĄD: nie znaleziono pliku {csv_path}")
            return 2
        log(f"Używam lokalnego pliku: {csv_path}")
    else:
        csv_path = cfg.csv_path
        status, download_info = download_csv(csv_path, meta, cfg.force or baseline)
        if status == "unchanged":
            log("Plik CSV nie zmienił się od ostatniego pobrania (HTTP 304) - koniec.")
            write_job_summary("### ISO Nowości\nPlik ISO nie zmienił się od ostatniego przebiegu.")
            return 0

    log("Analizuję CSV...")
    current, changes = scan_csv(csv_path, prev, cfg, baseline)
    log(f"Rekordów w bazie: {len(current)} (poprzednio: {len(prev)})")

    sender = DiscordSender(cfg)

    # --- pierwszy przebieg: tylko stan bazowy ------------------------------
    if baseline:
        if cfg.dry_run and not args.save_state:
            log(f"[dry-run] Stan bazowy ({len(current)} pozycji) NIE został zapisany.")
            return 0
        save_snapshot(cfg.snapshot_path, current)
        meta.update(download_info)
        meta.update({"last_run": datetime.now(timezone.utc).isoformat(),
                     "rows": len(current), "baseline": True})
        save_meta(cfg.meta_path, meta)
        log(f"Zapisano stan bazowy: {len(current)} pozycji.")
        if cfg.webhook and not cfg.dry_run:
            sender.send_embeds([build_info_embed(
                f"{KINDS['INFO']['icon']} Monitor ISO uruchomiony",
                f"Zapisano stan bazowy: **{len(current)}** pozycji z ISO Open Data.\n"
                f"Od następnego przebiegu będą przychodzić powiadomienia o zmianach:\n"
                f"{KINDS['NEW']['icon']} nowe normy {BULLET} "
                f"{KINDS['REVISION']['icon']} rewizje {BULLET} "
                f"{KINDS['WITHDRAWN']['icon']} wycofania {BULLET} "
                f"{KINDS['STAGE']['icon']} etapy DIS/FDIS",
                cfg)])
        write_job_summary(f"### ISO Nowości\nStan bazowy zapisany: **{len(current)}** pozycji.")
        return 0

    # --- filtry, sortowanie, limit ----------------------------------------
    found_total = len(changes)
    changes = apply_filters(changes, cfg)
    filtered_out = found_total - len(changes)
    changes.sort(key=lambda change: (KINDS[change.kind]["prio"], change.reference))
    summary = summary_line(changes)

    truncated = 0
    if cfg.max_messages > 0 and len(changes) > cfg.max_messages:
        truncated = len(changes) - cfg.max_messages
        changes = changes[: cfg.max_messages]

    message = f"Wykryto zmian: {found_total}"
    if filtered_out:
        message += f" (odfiltrowano: {filtered_out})"
    if truncated:
        message += f", wysyłam: {len(changes)}, pominięto z limitu: {truncated}"
    log(message)
    print_changes(changes)

    # --- wysyłka ----------------------------------------------------------
    all_ok = True
    if changes:
        embeds = [build_embed(change, cfg) for change in changes]
        if truncated:
            embeds.append(build_info_embed(
                f"{KINDS['INFO']['icon']} Pominięto {truncated} dalszych zmian",
                "Przekroczono limit powiadomień na jeden przebieg "
                f"(`MAX_MESSAGES={cfg.max_messages}`). Pozostałe zmiany zostały już zapisane "
                "w stanie i nie będą zgłoszone ponownie - zwiększ limit lub zawęź filtry, "
                "jeśli chcesz widzieć wszystko.", cfg))
        header = f"**Baza ISO {DASH} wykryto {len(changes) + truncated} zmian(y)**\n{summary}"
        all_ok = sender.send_embeds(embeds, header)
        if cfg.dry_run:
            log(f"[dry-run] Przygotowano {len(embeds)} powiadomień (nic nie wysłano).")
        else:
            log(f"Wysłano powiadomień: {sender.sent}, błędów: {sender.failed}")
    else:
        log("Brak nowych zmian do zgłoszenia.")

    # --- zapis stanu ------------------------------------------------------
    if cfg.dry_run and not args.save_state:
        log("[dry-run] Stan nie został zapisany.")
    elif not all_ok:
        log("BŁĄD: część powiadomień nie doszła - stan NIE został zapisany. "
            "Zmiany zostaną zgłoszone ponownie w kolejnym przebiegu.")
    else:
        save_snapshot(cfg.snapshot_path, current)
        meta.update(download_info)
        meta.update({"last_run": datetime.now(timezone.utc).isoformat(),
                     "rows": len(current), "baseline": False,
                     "last_changes": found_total})
        save_meta(cfg.meta_path, meta)
        log("Stan zapisany.")

    write_job_summary(
        "### ISO Nowości\n"
        f"- Rekordów w bazie: **{len(current)}**\n"
        f"- Wykrytych zmian: **{found_total}**\n"
        f"- Wysłanych powiadomień: **{sender.sent}**\n"
        f"- {summary}\n"
    )
    return 0 if all_ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("Przerwano.")
        sys.exit(130)
    except Exception as exc:                                          # noqa: BLE001
        log(f"BŁĄD KRYTYCZNY: {exc}")
        raise
