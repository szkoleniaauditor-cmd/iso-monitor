#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Codzienne sprawozdanie z monitora ISO — zwykła wiadomość tekstowa na Discord.

Świadomie NIE używa embedów: zwykła treść mieści się w limicie 2000 znaków
konta bez Nitro, a raport i tak jest zwięzły.

Raport jest niezależny od monitor.py i nie zmienia jego logiki. Trzyma własny
punkt odniesienia w state/raport_snapshot.csv i liczy różnicę między nim
a aktualnym stanem bazy ISO — dzięki temu obejmuje dokładnie okres od
poprzedniego raportu, niezależnie od tego, ile razy monitor się wykonał.

Uruchomienie:
    python raport.py                 # policz i wyślij
    python raport.py --dry-run       # tylko wypisz treść, nie wysyłaj
    python raport.py --csv plik.csv  # policz na lokalnym pliku CSV
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Sequence

import monitor

# --------------------------------------------------------------------------
# Stale
# --------------------------------------------------------------------------

DISCORD_LIMIT = 2000          # limit zwyklej wiadomosci (konto bez Nitro)
SAFETY_MARGIN = 40            # zapas, zeby nigdy nie otrzec sie o limit

SEPARATOR = "━" * 20

DNI_TYGODNIA = ["Poniedziałek", "Wtorek", "Środa", "Czwartek",
                "Piątek", "Sobota", "Niedziela"]

# Godziny (UTC), o ktorych monitor sprawdza baze - cron '0 1,5,9,13,17,21 * * *'.
# Celowo omijaja 19 i 20 UTC, zarezerwowane dla raportu (21:00 w Warszawie
# to 19:00 UTC latem i 20:00 UTC zima).
GODZINY_MONITORA = [1, 5, 9, 13, 17, 21]

SNAPSHOT_NAME = "raport_snapshot.csv"

# Kolejnosc i ikony sekcji w podsumowaniu
TYPY = [("NEW", "🆕"), ("REVISION", "🔄"), ("WITHDRAWN", "⛔"), ("STAGE", "⏳")]


# --------------------------------------------------------------------------
# Czas
# --------------------------------------------------------------------------


def strefa_pl():
    """Europe/Warsaw, z awaryjnym UTC+2 gdyby zabrakło bazy stref."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Europe/Warsaw")
    except Exception:                                                # noqa: BLE001
        return timezone(timedelta(hours=2))


def teraz_pl() -> datetime:
    return datetime.now(timezone.utc).astimezone(strefa_pl())


def naglowek_daty(chwila: datetime) -> str:
    """'Poniedziałek 25.08.2026'"""
    return f"{DNI_TYGODNIA[chwila.weekday()]} {chwila.strftime('%d.%m.%Y')}"


def nastepne_sprawdzenie(chwila_utc: Optional[datetime] = None) -> str:
    """Najblizszy przebieg monitora, opisany czasem polskim."""
    teraz = chwila_utc or datetime.now(timezone.utc)
    kandydaci = []
    for przesuniecie_dni in (0, 1):
        dzien = (teraz + timedelta(days=przesuniecie_dni)).date()
        for godzina in GODZINY_MONITORA:
            kandydat = datetime.combine(dzien, datetime.min.time(),
                                        tzinfo=timezone.utc).replace(hour=godzina)
            if kandydat > teraz:
                kandydaci.append(kandydat)
    if not kandydaci:
        return "wkrótce"

    nastepny = min(kandydaci).astimezone(strefa_pl())
    dzis_pl = teraz.astimezone(strefa_pl()).date()
    roznica = (nastepny.date() - dzis_pl).days
    kiedy = {0: "dziś", 1: "jutro"}.get(roznica, nastepny.strftime("%d.%m"))
    return f"{kiedy} o {nastepny.strftime('%H:%M')}"


# --------------------------------------------------------------------------
# Skladanie tresci
# --------------------------------------------------------------------------


def liczba_z_odstepami(wartosc: int) -> str:
    """81323 -> '81 323'"""
    return f"{wartosc:,}".replace(",", " ")


def opis_zmiany(zmiana: monitor.Change, limit_tytulu: int = 46) -> str:
    """'🆕 ISO 45006:2026 - Occupational health'"""
    ikona = monitor.KINDS[zmiana.kind]["icon"]
    if zmiana.kind == "WITHDRAWN":
        opis = "wycofana"
    else:
        opis = monitor.trim(zmiana.title, limit_tytulu) or "bez tytułu"
    return f"{ikona} {zmiana.reference} - {opis}"


def zbuduj_raport(zmiany: List[monitor.Change], rekordow: int,
                  chwila: Optional[datetime] = None) -> str:
    """Sklada raport tak, by zmiescil sie w limicie 2000 znakow."""
    chwila = chwila or teraz_pl()
    licznik = monitor.counts_by_kind(zmiany)

    naglowek = [
        f"📋 RAPORT ISO | {naglowek_daty(chwila)}",
        SEPARATOR,
        f"📊 Sprawdzono: {liczba_z_odstepami(rekordow)} norm",
        f"🔔 Zmian dzisiaj: {len(zmiany)}",
    ]
    if zmiany:
        rozbicie = "   ".join(f"{ikona} {licznik.get(kind, 0)}" for kind, ikona in TYPY)
        naglowek.append(f"   {rozbicie}")

    stopka = [
        "",
        f"⏰ Następne sprawdzenie: {nastepne_sprawdzenie()}",
        SEPARATOR,
    ]

    if not zmiany:
        srodek = ["", "😴 ISO spokojne — brak nowości."]
        return "\n".join(naglowek + srodek + stopka)

    # ile miejsca zostaje na liste zmian
    szkielet = "\n".join(naglowek + [""] + stopka)
    budzet = DISCORD_LIMIT - len(szkielet) - SAFETY_MARGIN

    linie: List[str] = []
    uzyte = 0
    for numer, zmiana in enumerate(zmiany):
        linia = opis_zmiany(zmiana)
        pozostalo = len(zmiany) - numer
        # zostaw miejsce na dopisek o pominietych, jesli cos jeszcze zostanie
        rezerwa = len(f"…i {pozostalo} więcej\n") if pozostalo > 1 else 0
        if uzyte + len(linia) + 1 + rezerwa > budzet:
            linie.append(f"…i {pozostalo} więcej")
            break
        linie.append(linia)
        uzyte += len(linia) + 1

    tresc = "\n".join(naglowek + [""] + linie + stopka)
    if len(tresc) > DISCORD_LIMIT:                    # pas bezpieczenstwa
        tresc = tresc[: DISCORD_LIMIT - 1].rstrip() + "…"
    return tresc


# --------------------------------------------------------------------------
# Wysylka
# --------------------------------------------------------------------------


def wyslij(tresc: str, cfg: monitor.Config) -> bool:
    """Zwykla wiadomosc tekstowa - bez embedow."""
    sender = monitor.DiscordSender(cfg)
    payload = {
        "content": tresc,
        "allowed_mentions": {"parse": []},
    }
    if cfg.username:
        payload["username"] = cfg.username
    if cfg.icon_url:
        payload["avatar_url"] = cfg.icon_url
    return sender._post(payload)          # ta sama obsluga limitow co w monitorze


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Codzienny raport ISO -> Discord")
    parser.add_argument("--dry-run", action="store_true",
                        help="wypisz raport, nie wysylaj i nie zapisuj punktu odniesienia")
    parser.add_argument("--csv", dest="csv_file", default=None,
                        help="uzyj lokalnego pliku CSV zamiast pobierania")
    parser.add_argument("--state-dir", default=None, help="katalog stanu (domyslnie ./state)")
    parser.add_argument("--data-dir", default=None, help="katalog na pobrany CSV (domyslnie ./data)")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[attr-defined]
    except Exception:                                                # noqa: BLE001
        pass

    monitor.raise_csv_field_limit()
    args = parse_args(argv)

    # Config budujemy tak samo jak monitor - te same filtry i ten sam webhook
    cfg = monitor.build_config(monitor.parse_args(["--dry-run"] if args.dry_run else []))
    if args.state_dir:
        cfg.state_dir = Path(args.state_dir)
    if args.data_dir:
        cfg.data_dir = Path(args.data_dir)
    cfg.dry_run = args.dry_run
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)

    if not cfg.webhook and not args.dry_run:
        monitor.log("BŁĄD: brak zmiennej środowiskowej DISCORD_WEBHOOK_URL.")
        return 2

    punkt_odniesienia = cfg.state_dir / SNAPSHOT_NAME

    # --- skad brac dane ----------------------------------------------------
    if args.csv_file:
        csv_path = Path(args.csv_file)
        if not csv_path.exists():
            monitor.log(f"BŁĄD: nie znaleziono pliku {csv_path}")
            return 2
        monitor.log(f"Używam lokalnego pliku: {csv_path}")
    else:
        csv_path = cfg.csv_path
        # raport chodzi raz dziennie - pobieramy zawsze, bez gry w ETag
        status, _info = monitor.download_csv(csv_path, {}, force=True)
        if status != "ok":
            monitor.log("BŁĄD: nie udało się pobrać danych ISO.")
            return 1

    # --- punkt odniesienia -------------------------------------------------
    poprzedni = monitor.load_snapshot(punkt_odniesienia)
    if not poprzedni:
        # pierwszy raport: zacznij od stanu monitora, jesli istnieje
        stan_monitora = cfg.snapshot_path
        if stan_monitora.exists():
            poprzedni = monitor.load_snapshot(stan_monitora)
            monitor.log(f"Pierwszy raport — punktem odniesienia jest stan monitora "
                        f"({len(poprzedni)} pozycji).")
        else:
            monitor.log("Pierwszy raport i brak stanu monitora — zapisuję punkt odniesienia.")

    baseline = not poprzedni
    aktualny, zmiany = monitor.scan_csv(csv_path, poprzedni, cfg, baseline)
    monitor.log(f"Rekordów w bazie: {len(aktualny)} | zmian od ostatniego raportu: {len(zmiany)}")

    zmiany = monitor.apply_filters(zmiany, cfg)
    zmiany.sort(key=lambda z: (monitor.KINDS[z.kind]["prio"], z.reference))

    tresc = zbuduj_raport(zmiany, len(aktualny))
    monitor.log(f"Długość wiadomości: {len(tresc)}/{DISCORD_LIMIT} znaków")
    print("-" * 60)
    print(tresc)
    print("-" * 60)

    # --- wysylka i zapis ---------------------------------------------------
    if args.dry_run:
        monitor.log("[dry-run] Nie wysłano i nie zapisano punktu odniesienia.")
        return 0

    if not wyslij(tresc, cfg):
        monitor.log("BŁĄD: nie udało się wysłać raportu — punkt odniesienia bez zmian.")
        return 1
    monitor.log("Raport wysłany na Discord.")

    monitor.save_snapshot(punkt_odniesienia, aktualny)
    monitor.log(f"Zapisano punkt odniesienia: {len(aktualny)} pozycji.")

    monitor.write_job_summary(
        f"### Raport dzienny ISO\n"
        f"- Rekordów w bazie: **{len(aktualny)}**\n"
        f"- Zmian w raporcie: **{len(zmiany)}**\n"
        f"- Długość wiadomości: **{len(tresc)}/{DISCORD_LIMIT}** znaków\n"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        monitor.log("Przerwano.")
        sys.exit(130)
    except Exception as exc:                                          # noqa: BLE001
        monitor.log(f"BŁĄD KRYTYCZNY: {exc}")
        raise
