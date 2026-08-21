#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ISO Monitor — aplikacja okienkowa do monitorowania nowości w bazie norm ISO.

Nakładka graficzna na logikę z monitor.py:
  * pobiera plik CSV z ISO Open Data i porównuje go z poprzednim pobraniem,
  * pokazuje wykryte zmiany jako listę kart (nowe / rewizje / wycofania / DIS-FDIS),
  * opcjonalnie wysyła powiadomienia na Discord,
  * chodzi w tle i sprawdza bazę co zadaną liczbę godzin,
  * chowa się do zasobnika systemowego (obok zegarka).

Ustawienia i stan trzymane są w:  %APPDATA%\\ISO Monitor\\
"""

from __future__ import annotations

import os
import sys

# W trybie --windowed (bez konsoli) PyInstaller ustawia stdout/stderr na None,
# a każde print() rzuca wtedy wyjątkiem. Musi być przed importami bibliotek.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

import json
import queue
import threading
import time
import traceback
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import customtkinter as ctk
import pystray
from PIL import Image, ImageTk

import monitor

APP_TITLE = "ISO Monitor"
APP_VERSION = "1.0"

# Kolory pasujące do powiadomień na Discordzie
COLORS = {
    "NEW":       "#2ECC71",
    "REVISION":  "#3498DB",
    "WITHDRAWN": "#E74C3C",
    "STAGE":     "#F39C12",
    "INFO":      "#7F8C8D",
}

# W oknie zamiast emoji (Tk na Windows rysuje je jako puste kwadraty)
BADGES = {
    "NEW":       "NOWA",
    "REVISION":  "REWIZJA",
    "WITHDRAWN": "WYCOFANA",
    "STAGE":     "DIS/FDIS",
    "INFO":      "INFO",
}

DEFAULT_CONFIG = {
    "webhook": "",
    "send_to_discord": True,
    "interval_hours": 4,
    "check_on_start": True,
    "minimize_to_tray": True,
    "max_messages": 250,
    "watch_prefixes": "40,50",
    "notify_all_stages": False,
    "ignore_deleted": True,
    "filter_committees": "",
    "filter_types": "",
    "filter_keywords": "",
}


# --------------------------------------------------------------------------
# Ścieżki i ustawienia
# --------------------------------------------------------------------------


def resource_path(name: str) -> Path:
    """Plik dołączony do aplikacji — działa i ze źródeł, i z .exe."""
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        candidate = Path(bundled) / name
        if candidate.exists():
            return candidate
    return Path(__file__).resolve().parent / name


def app_dir() -> Path:
    base = os.getenv("APPDATA") or str(Path.home())
    path = Path(base) / APP_TITLE
    path.mkdir(parents=True, exist_ok=True)
    return path


def diag(msg: str) -> None:
    """Log techniczny do pliku — w wersji .exe nie ma konsoli, na którą można pisać."""
    try:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with (app_dir() / "diagnostyka.log").open("a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {msg}\n")
    except Exception:
        pass


def config_path() -> Path:
    return app_dir() / "config.json"


def load_config() -> dict:
    data = dict(DEFAULT_CONFIG)
    try:
        if config_path().exists():
            stored = json.loads(config_path().read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                data.update({k: v for k, v in stored.items() if k in DEFAULT_CONFIG})
    except (ValueError, OSError):
        pass
    return data


def save_config(data: dict) -> None:
    try:
        config_path().write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{num:.1f} {unit}" if unit != "B" else f"{int(num)} B"
        num /= 1024
    return f"{num:.1f} GB"


# --------------------------------------------------------------------------
# Okno główne
# --------------------------------------------------------------------------


class IsoMonitorApp(ctk.CTk):

    def __init__(self, selftest: bool = False) -> None:
        super().__init__()
        self.selftest = selftest
        self.settings = load_config()
        self.events: "queue.Queue[tuple]" = queue.Queue()
        self.busy = False
        self.tray: Optional[pystray.Icon] = None
        self.next_check_at: Optional[float] = None
        self.last_changes: List[monitor.Change] = []
        self._icon_ref = None

        # Log z monitor.py przekierowany do okna (w trybie .exe nie ma konsoli)
        monitor.log = self._log_from_monitor
        monitor.raise_csv_field_limit()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title(f"{APP_TITLE} {APP_VERSION}")
        self.geometry("980x720")
        self.minsize(880, 620)
        self._apply_window_icon()

        # Kolejność ma znaczenie: stopka musi zarezerwować pas na dole ZANIM
        # rozciągliwy tabview zajmie całą pozostałą przestrzeń.
        self._build_header()
        self._build_stats()
        self._build_footer()
        self._build_tabs()

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(120, self._pump_events)

        self._restore_last_state()

        if not selftest:
            self._start_tray()
            self._schedule_next_check()
            if self.settings["check_on_start"]:
                self.after(900, lambda: self.start_check(reason="start aplikacji"))

    # ---------------------------------------------------------------- ikona

    def _apply_window_icon(self) -> None:
        diag(f"start | zamrożone={getattr(sys, 'frozen', False)} | "
             f"_MEIPASS={getattr(sys, '_MEIPASS', '-')} | __file__={__file__}")
        ico, png = resource_path("ikona.ico"), resource_path("ikona.png")
        diag(f"ikona.ico -> {ico} (istnieje: {ico.exists()})")
        diag(f"ikona.png -> {png} (istnieje: {png.exists()})")
        try:
            if ico.exists():
                self.iconbitmap(str(ico))
                diag("iconbitmap OK")
                return
        except Exception as exc:                                     # noqa: BLE001
            diag(f"iconbitmap BŁĄD: {type(exc).__name__}: {exc}")
        try:
            if png.exists():
                self._icon_ref = ImageTk.PhotoImage(Image.open(png))
                self.iconphoto(True, self._icon_ref)
                diag("iconphoto OK")
        except Exception as exc:                                     # noqa: BLE001
            diag(f"iconphoto BŁĄD: {type(exc).__name__}: {exc}")

    # ------------------------------------------------------------- budowa UI

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, height=92, corner_radius=0, fg_color=("gray86", "gray14"))
        header.pack(fill="x")
        header.pack_propagate(False)

        left = ctk.CTkFrame(header, fg_color="transparent")
        left.pack(side="left", padx=18, pady=14)

        try:
            img = Image.open(resource_path("ikona.png")).convert("RGBA")
            logo = ctk.CTkImage(light_image=img, dark_image=img, size=(60, 60))
            ctk.CTkLabel(left, image=logo, text="").pack(side="left", padx=(0, 14))
            self._logo_ref = logo
            diag("logo w nagłówku OK")
        except Exception as exc:                                     # noqa: BLE001
            diag(f"logo w nagłówku BŁĄD: {type(exc).__name__}: {exc}")

        titles = ctk.CTkFrame(left, fg_color="transparent")
        titles.pack(side="left")
        ctk.CTkLabel(titles, text=APP_TITLE,
                     font=ctk.CTkFont(size=24, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(titles, text="Monitor nowości w bazie norm ISO",
                     font=ctk.CTkFont(size=13),
                     text_color=("gray40", "gray65")).pack(anchor="w")

        right = ctk.CTkFrame(header, fg_color="transparent")
        right.pack(side="right", padx=18)
        self.next_label = ctk.CTkLabel(right, text="", font=ctk.CTkFont(size=12),
                                       text_color=("gray40", "gray65"))
        self.next_label.pack(anchor="e", pady=(6, 0))
        self.discord_label = ctk.CTkLabel(right, text="", font=ctk.CTkFont(size=12))
        self.discord_label.pack(anchor="e")

    def _build_stats(self) -> None:
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(14, 6))

        self.stat_widgets = {}
        specs = [
            ("rows", "Pozycji w bazie", "—"),
            ("last", "Ostatnie sprawdzenie", "nigdy"),
            ("found", "Zmian ostatnio", "—"),
            ("sent", "Wysłano na Discord", "—"),
        ]
        # grid z uniform: cztery kolumny zawsze równej szerokości, niezależnie
        # od długości tekstu i skalowania DPI — inaczej ostatnia karta ucieka poza okno
        for index, (key, caption, value) in enumerate(specs):
            row.grid_columnconfigure(index, weight=1, uniform="stat")
            card = ctk.CTkFrame(row, corner_radius=10, fg_color=("gray92", "gray17"))
            card.grid(row=0, column=index, sticky="nsew", padx=5)
            ctk.CTkLabel(card, text=caption, font=ctk.CTkFont(size=11), anchor="w",
                         text_color=("gray45", "gray60")).pack(anchor="w", fill="x",
                                                               padx=14, pady=(10, 0))
            label = ctk.CTkLabel(card, text=value, anchor="w",
                                 font=ctk.CTkFont(size=18, weight="bold"))
            label.pack(anchor="w", fill="x", padx=14, pady=(0, 10))
            self.stat_widgets[key] = label

    def _build_tabs(self) -> None:
        self.tabs = ctk.CTkTabview(self, corner_radius=10)
        self.tabs.pack(fill="both", expand=True, padx=16, pady=6)
        self.tabs.add("Zmiany")
        self.tabs.add("Dziennik")
        self.tabs.add("Ustawienia")

        # --- zakładka: zmiany ---
        self.changes_frame = ctk.CTkScrollableFrame(self.tabs.tab("Zmiany"),
                                                    fg_color="transparent")
        self.changes_frame.pack(fill="both", expand=True)
        self.empty_label = ctk.CTkLabel(
            self.changes_frame,
            text="Brak wykrytych zmian.\n\nKliknij „Sprawdź teraz”, aby pobrać dane z ISO Open Data.",
            font=ctk.CTkFont(size=13), text_color=("gray45", "gray60"), justify="center")
        self.empty_label.pack(pady=60)

        # --- zakładka: dziennik ---
        self.log_box = ctk.CTkTextbox(self.tabs.tab("Dziennik"),
                                      font=ctk.CTkFont(family="Consolas", size=12),
                                      wrap="none")
        self.log_box.pack(fill="both", expand=True)
        self.log_box.configure(state="disabled")

        # --- zakładka: ustawienia ---
        self._build_settings(self.tabs.tab("Ustawienia"))

    def _build_settings(self, parent) -> None:
        frame = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        frame.pack(fill="both", expand=True)

        def section(text: str) -> None:
            ctk.CTkLabel(frame, text=text, font=ctk.CTkFont(size=15, weight="bold")
                         ).pack(anchor="w", pady=(16, 6))

        def hint(text: str) -> None:
            ctk.CTkLabel(frame, text=text, font=ctk.CTkFont(size=11),
                         text_color=("gray45", "gray60"), justify="left",
                         wraplength=820).pack(anchor="w", pady=(0, 4))

        self.vars = {}

        section("Discord")
        hint("Adres webhooka z Discorda: Edytuj kanał → Integracje → Webhooki → Kopiuj URL. "
             "Zostawienie pustego pola wyłącza wysyłkę — zmiany i tak zobaczysz w zakładce „Zmiany”.")
        self.vars["webhook"] = ctk.StringVar(value=self.settings["webhook"])
        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.pack(fill="x", pady=(0, 6))
        ctk.CTkEntry(row, textvariable=self.vars["webhook"], show="•",
                     placeholder_text="https://discord.com/api/webhooks/...").pack(
            side="left", fill="x", expand=True)
        ctk.CTkButton(row, text="Wyślij test", width=110,
                      command=self.test_webhook).pack(side="left", padx=(8, 0))

        self.vars["send_to_discord"] = ctk.BooleanVar(value=self.settings["send_to_discord"])
        ctk.CTkCheckBox(frame, text="Wysyłaj powiadomienia na Discord",
                        variable=self.vars["send_to_discord"]).pack(anchor="w", pady=4)

        section("Sprawdzanie")
        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.pack(fill="x", pady=4)
        ctk.CTkLabel(row, text="Co ile godzin sprawdzać:", width=210,
                     anchor="w").pack(side="left")
        self.vars["interval_hours"] = ctk.StringVar(value=str(self.settings["interval_hours"]))
        ctk.CTkOptionMenu(row, values=["1", "2", "4", "6", "12", "24"],
                          variable=self.vars["interval_hours"], width=90).pack(side="left")

        self.vars["check_on_start"] = ctk.BooleanVar(value=self.settings["check_on_start"])
        ctk.CTkCheckBox(frame, text="Sprawdź od razu po uruchomieniu aplikacji",
                        variable=self.vars["check_on_start"]).pack(anchor="w", pady=4)

        self.vars["minimize_to_tray"] = ctk.BooleanVar(value=self.settings["minimize_to_tray"])
        ctk.CTkCheckBox(frame, text="Zamknięcie okna chowa aplikację do zasobnika "
                                    "(zamiast kończyć program)",
                        variable=self.vars["minimize_to_tray"]).pack(anchor="w", pady=4)

        section("Co zgłaszać")
        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.pack(fill="x", pady=4)
        ctk.CTkLabel(row, text="Etapy zgłaszane jako DIS/FDIS:", width=210,
                     anchor="w").pack(side="left")
        self.vars["watch_prefixes"] = ctk.StringVar(value=self.settings["watch_prefixes"])
        ctk.CTkEntry(row, textvariable=self.vars["watch_prefixes"], width=140).pack(side="left")
        hint("40 = DIS (ankieta publiczna), 50 = FDIS (końcowe zatwierdzenie). "
             "Dodaj 60, aby dostawać też sygnał „norma w trakcie publikacji”.")

        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.pack(fill="x", pady=4)
        ctk.CTkLabel(row, text="Limit powiadomień na przebieg:", width=210,
                     anchor="w").pack(side="left")
        self.vars["max_messages"] = ctk.StringVar(value=str(self.settings["max_messages"]))
        ctk.CTkEntry(row, textvariable=self.vars["max_messages"], width=140).pack(side="left")

        self.vars["notify_all_stages"] = ctk.BooleanVar(value=self.settings["notify_all_stages"])
        ctk.CTkCheckBox(frame, text="Zgłaszaj każdą zmianę etapu (nie tylko DIS/FDIS) — "
                                    "bardzo dużo powiadomień",
                        variable=self.vars["notify_all_stages"]).pack(anchor="w", pady=4)

        self.vars["ignore_deleted"] = ctk.BooleanVar(value=self.settings["ignore_deleted"])
        ctk.CTkCheckBox(frame, text="Pomijaj projekty porzucone (podetap .98)",
                        variable=self.vars["ignore_deleted"]).pack(anchor="w", pady=4)

        section("Filtry (puste = wszystko)")
        for key, caption, placeholder in [
            ("filter_committees", "Komitety:", "ISO/TC 176, ISO/IEC JTC 1/SC 27"),
            ("filter_types", "Typy dokumentów:", "IS, TS, TR"),
            ("filter_keywords", "Słowa kluczowe:", "security, quality"),
        ]:
            row = ctk.CTkFrame(frame, fg_color="transparent")
            row.pack(fill="x", pady=4)
            ctk.CTkLabel(row, text=caption, width=210, anchor="w").pack(side="left")
            self.vars[key] = ctk.StringVar(value=self.settings[key])
            ctk.CTkEntry(row, textvariable=self.vars[key],
                         placeholder_text=placeholder).pack(side="left", fill="x", expand=True)

        buttons = ctk.CTkFrame(frame, fg_color="transparent")
        buttons.pack(fill="x", pady=(20, 10))
        ctk.CTkButton(buttons, text="Zapisz ustawienia", width=170,
                      command=self.save_settings).pack(side="left")
        ctk.CTkButton(buttons, text="Otwórz folder danych", width=170,
                      fg_color="transparent", border_width=1,
                      command=lambda: os.startfile(str(app_dir()))).pack(side="left", padx=8)
        ctk.CTkButton(buttons, text="Skasuj zapisany stan", width=170,
                      fg_color="transparent", border_width=1,
                      command=self.reset_state).pack(side="left")
        self.settings_status = ctk.CTkLabel(frame, text="", font=ctk.CTkFont(size=12))
        self.settings_status.pack(anchor="w", pady=(0, 10))

    def _build_footer(self) -> None:
        footer = ctk.CTkFrame(self, height=68, corner_radius=0, fg_color=("gray86", "gray14"))
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)

        self.check_button = ctk.CTkButton(footer, text="Sprawdź teraz", width=150, height=36,
                                          font=ctk.CTkFont(size=14, weight="bold"),
                                          command=lambda: self.start_check(reason="ręcznie"))
        self.check_button.pack(side="left", padx=(18, 8), pady=16)

        self.tray_button = ctk.CTkButton(footer, text="Ukryj do zasobnika", width=160, height=36,
                                         fg_color="transparent", border_width=1,
                                         command=self.hide_to_tray)
        self.tray_button.pack(side="left", pady=16)

        self.progress = ctk.CTkProgressBar(footer, height=8)
        self.progress.set(0)
        self.progress.pack(side="left", fill="x", expand=True, padx=18)

        self.status_label = ctk.CTkLabel(footer, text="Gotowe", font=ctk.CTkFont(size=12),
                                         text_color=("gray40", "gray65"))
        self.status_label.pack(side="right", padx=18)

    # ------------------------------------------------------------ zdarzenia

    def _post(self, kind: str, payload=None) -> None:
        self.events.put((kind, payload))

    def _log_from_monitor(self, msg: str) -> None:
        self._post("log", msg)

    def _pump_events(self) -> None:
        """Jedyne miejsce, w którym wątek roboczy dotyka interfejsu."""
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self.append_log(payload)
                elif kind == "status":
                    self.status_label.configure(text=payload)
                elif kind == "progress":
                    done, total = payload
                    if total:
                        self.progress.set(min(1.0, done / total))
                        self.status_label.configure(
                            text=f"Pobieranie {human_size(done)} / {human_size(total)}")
                elif kind == "done":
                    self._on_worker_done(payload)
                elif kind == "done_test":
                    self._on_test_done(payload)
                elif kind == "error":
                    self._on_worker_error(payload)
        except queue.Empty:
            pass
        self._update_next_label()
        self.after(150, self._pump_events)

    def append_log(self, msg: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[{stamp}] {msg}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    # -------------------------------------------------------- praca w tle

    def start_check(self, reason: str = "", force: bool = False) -> None:
        if self.busy:
            return
        self.busy = True
        self.check_button.configure(state="disabled", text="Sprawdzam…")
        self.progress.set(0)
        self.status_label.configure(text="Łączenie z ISO Open Data…")
        self.append_log(f"--- Sprawdzanie ({reason or 'automatyczne'}) ---")
        threading.Thread(target=self._worker, args=(force,), daemon=True).start()

    def build_cfg(self) -> monitor.Config:
        data = self.settings
        base = app_dir()

        def as_list(text: str, upper=False, lower=False) -> List[str]:
            parts = [p.strip() for p in str(text).split(",") if p.strip()]
            if upper:
                return [p.upper() for p in parts]
            if lower:
                return [p.lower() for p in parts]
            return parts

        try:
            max_messages = int(str(data["max_messages"]).strip() or 250)
        except ValueError:
            max_messages = 250

        return monitor.Config(
            webhook=str(data["webhook"]).strip(),
            state_dir=base / "state",
            data_dir=base / "data",
            dry_run=False,
            baseline=False,
            force=False,
            max_messages=max_messages,
            watch_prefixes=as_list(data["watch_prefixes"]) or ["40", "50"],
            notify_all_stages=bool(data["notify_all_stages"]),
            ignore_deleted=bool(data["ignore_deleted"]),
            committees=as_list(data["filter_committees"], upper=True),
            types=as_list(data["filter_types"], upper=True),
            keywords=as_list(data["filter_keywords"], lower=True),
            icon_url=(os.getenv("ICON_URL") or "").strip(),
            username=APP_TITLE,
        )

    def _worker(self, force: bool) -> None:
        try:
            cfg = self.build_cfg()
            cfg.state_dir.mkdir(parents=True, exist_ok=True)
            cfg.data_dir.mkdir(parents=True, exist_ok=True)

            meta = monitor.load_meta(cfg.meta_path)
            prev = monitor.load_snapshot(cfg.snapshot_path)
            baseline = not prev

            status, info = monitor.download_csv(
                cfg.csv_path, meta, force or baseline,
                progress=lambda done, total: self._post("progress", (done, total)))

            if status == "unchanged":
                self._post("done", {"kind": "unchanged"})
                return

            self._post("status", "Analizowanie danych…")
            current, changes = monitor.scan_csv(cfg.csv_path, prev, cfg, baseline)

            if baseline:
                monitor.save_snapshot(cfg.snapshot_path, current)
                meta.update(info)
                meta.update({"last_run": datetime.now().astimezone().isoformat(),
                             "rows": len(current), "baseline": True})
                monitor.save_meta(cfg.meta_path, meta)
                self._post("done", {"kind": "baseline", "rows": len(current)})
                return

            found = len(changes)
            changes = monitor.apply_filters(changes, cfg)
            changes.sort(key=lambda c: (monitor.KINDS[c.kind]["prio"], c.reference))

            truncated = 0
            if cfg.max_messages > 0 and len(changes) > cfg.max_messages:
                truncated = len(changes) - cfg.max_messages
                changes = changes[: cfg.max_messages]

            sent, ok = 0, True
            wants_discord = bool(cfg.webhook) and bool(self.settings["send_to_discord"])
            if changes and wants_discord:
                self._post("status", f"Wysyłanie {len(changes)} powiadomień na Discord…")
                sender = monitor.DiscordSender(cfg)
                embeds = [monitor.build_embed(c, cfg) for c in changes]
                header = (f"**Baza ISO {monitor.DASH} wykryto {found} zmian(y)**\n"
                          f"{monitor.summary_line(changes)}")
                ok = sender.send_embeds(embeds, header)
                sent = sender.sent

            if ok:
                monitor.save_snapshot(cfg.snapshot_path, current)
                meta.update(info)
                meta.update({"last_run": datetime.now().astimezone().isoformat(),
                             "rows": len(current), "baseline": False,
                             "last_changes": found})
                monitor.save_meta(cfg.meta_path, meta)
            else:
                monitor.log("Część powiadomień nie doszła — stan NIE został zapisany, "
                            "zmiany wrócą przy następnym sprawdzeniu.")

            self._post("done", {"kind": "changes", "changes": changes, "rows": len(current),
                                "found": found, "sent": sent, "ok": ok, "truncated": truncated})
        except Exception as exc:                                     # noqa: BLE001
            self._post("error", f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}")

    def _finish_busy(self) -> None:
        self.busy = False
        self.check_button.configure(state="normal", text="Sprawdź teraz")
        self.progress.set(0)
        self._schedule_next_check()

    def _on_worker_done(self, result: dict) -> None:
        kind = result.get("kind")
        now = datetime.now().strftime("%d.%m.%Y %H:%M")
        self.stat_widgets["last"].configure(text=now)

        if kind == "unchanged":
            self.append_log("Plik ISO nie zmienił się od ostatniego sprawdzenia (HTTP 304).")
            self.status_label.configure(text="Brak zmian w źródle")
        elif kind == "baseline":
            rows = result["rows"]
            self.stat_widgets["rows"].configure(text=f"{rows:,}".replace(",", " "))
            self.stat_widgets["found"].configure(text="0")
            self.stat_widgets["sent"].configure(text="0")
            self.append_log(f"Zapisano stan bazowy: {rows} pozycji. "
                            "Od następnego sprawdzenia zobaczysz tu zmiany.")
            self.status_label.configure(text="Zapisano stan bazowy")
            self._show_empty("Zapisano stan bazowy — pobrano całą bazę ISO.\n\n"
                             "Kolejne sprawdzenia pokażą tutaj wyłącznie to, co się zmieniło.")
        elif kind == "changes":
            rows, found, sent = result["rows"], result["found"], result["sent"]
            self.stat_widgets["rows"].configure(text=f"{rows:,}".replace(",", " "))
            self.stat_widgets["found"].configure(text=str(found))
            self.stat_widgets["sent"].configure(text=str(sent))
            self.last_changes = result["changes"]
            self._render_changes(result["changes"])
            if found:
                self.append_log(f"Wykryto zmian: {found}, wysłano na Discord: {sent}.")
                self.status_label.configure(text=f"Wykryto {found} zmian")
                self.tabs.set("Zmiany")
                if self.tray:
                    self._notify_tray(f"Wykryto {found} zmian w bazie ISO")
            else:
                self.append_log("Brak nowych zmian.")
                self.status_label.configure(text="Brak nowych zmian")
            if result.get("truncated"):
                self.append_log(f"Pominięto {result['truncated']} zmian z powodu limitu "
                                "powiadomień (zmień go w Ustawieniach).")
            if not result.get("ok", True):
                self.status_label.configure(text="Błąd wysyłki na Discord")

        self._finish_busy()

    def _on_worker_error(self, message: str) -> None:
        self.append_log(f"BŁĄD: {message}")
        self.status_label.configure(text="Wystąpił błąd — szczegóły w Dzienniku")
        self.tabs.set("Dziennik")
        self._finish_busy()

    # -------------------------------------------------------- lista zmian

    def _clear_changes(self) -> None:
        for widget in self.changes_frame.winfo_children():
            widget.destroy()

    def _show_empty(self, text: str) -> None:
        self._clear_changes()
        self.empty_label = ctk.CTkLabel(self.changes_frame, text=text,
                                        font=ctk.CTkFont(size=13),
                                        text_color=("gray45", "gray60"), justify="center")
        self.empty_label.pack(pady=60)

    def _render_changes(self, changes: List[monitor.Change]) -> None:
        self._clear_changes()
        if not changes:
            self._show_empty("Brak nowych zmian przy ostatnim sprawdzeniu.\n\n"
                             "Baza ISO nie zmieniła się od poprzedniego pobrania.")
            return
        for change in changes[:300]:
            self._add_change_card(change)
        if len(changes) > 300:
            ctk.CTkLabel(self.changes_frame,
                         text=f"…oraz {len(changes) - 300} kolejnych "
                              "(pełna lista trafiła na Discorda)",
                         text_color=("gray45", "gray60")).pack(pady=10)

    def _add_change_card(self, change: monitor.Change) -> None:
        color = COLORS.get(change.kind, COLORS["INFO"])

        card = ctk.CTkFrame(self.changes_frame, corner_radius=8, fg_color=("gray92", "gray17"))
        card.pack(fill="x", padx=2, pady=4)

        # height=1 jest konieczne: pusty CTkFrame ma domyślnie 200 px wysokości,
        # a nie mając dzieci nie skurczy się sam i rozpycha całą kartę.
        stripe = ctk.CTkFrame(card, width=6, height=1, corner_radius=3, fg_color=color)
        stripe.pack(side="left", fill="y", padx=(0, 12), pady=2)

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(side="left", fill="both", expand=True, pady=11)

        top = ctk.CTkFrame(body, fg_color="transparent")
        top.pack(fill="x")
        ctk.CTkLabel(top, text=BADGES.get(change.kind, "?"), fg_color=color, corner_radius=4,
                     text_color="#0f1216", width=86, height=21,
                     font=ctk.CTkFont(size=11, weight="bold")).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(top, text=change.reference,
                     font=ctk.CTkFont(size=14, weight="bold"), anchor="w").pack(side="left")

        if change.title:
            ctk.CTkLabel(body, text=monitor.trim(change.title, 260),
                         font=ctk.CTkFont(size=12), justify="left", anchor="w",
                         wraplength=640).pack(anchor="w", pady=(4, 2))

        bits = []
        if change.pub_date:
            bits.append(f"Data: {change.pub_date}")
        if change.committee:
            bits.append(f"Komitet: {change.committee}")
        if change.old_stage and change.new_stage:
            bits.append(f"Etap: {monitor.stage_dotted(change.old_stage)} → "
                        f"{monitor.stage_dotted(change.new_stage)}")
        elif change.new_stage:
            bits.append(f"Etap: {monitor.stage_dotted(change.new_stage)} "
                        f"({monitor.stage_label(change.new_stage)})")
        if bits:
            ctk.CTkLabel(body, text="   •   ".join(bits), font=ctk.CTkFont(size=11),
                         text_color=("gray45", "gray60"), anchor="w",
                         justify="left", wraplength=640).pack(anchor="w")

        side = ctk.CTkFrame(card, fg_color="transparent")
        side.pack(side="right", padx=12)
        ctk.CTkButton(side, text="Otwórz w ISO", width=120, height=30,
                      command=lambda url=change.url: webbrowser.open(url)).pack(pady=14)

    # ------------------------------------------------------------ ustawienia

    def save_settings(self) -> None:
        for key, var in self.vars.items():
            self.settings[key] = var.get()
        try:
            self.settings["interval_hours"] = int(str(self.settings["interval_hours"]))
        except ValueError:
            self.settings["interval_hours"] = 4
        try:
            self.settings["max_messages"] = int(str(self.settings["max_messages"]).strip() or 250)
        except ValueError:
            self.settings["max_messages"] = 250
        save_config(self.settings)
        self.settings_status.configure(text="Zapisano ustawienia.",
                                       text_color=COLORS["NEW"])
        self.after(2500, lambda: self.settings_status.configure(text=""))
        self.append_log("Zapisano ustawienia.")
        self._schedule_next_check()
        self._update_discord_label()

    def reset_state(self) -> None:
        cfg = self.build_cfg()
        removed = 0
        for path in (cfg.snapshot_path, cfg.meta_path):
            try:
                if path.exists():
                    path.unlink()
                    removed += 1
            except OSError:
                pass
        self.settings_status.configure(
            text=f"Skasowano zapisany stan ({removed} plik/i). "
                 "Kolejne sprawdzenie zbuduje bazę od nowa.",
            text_color=COLORS["STAGE"])
        self.append_log("Skasowano zapisany stan.")

    def test_webhook(self) -> None:
        url = self.vars["webhook"].get().strip()
        if not url:
            self.settings_status.configure(text="Najpierw wklej adres webhooka.",
                                           text_color=COLORS["WITHDRAWN"])
            return
        self.settings_status.configure(text="Wysyłanie wiadomości testowej…",
                                       text_color=("gray45", "gray60"))

        def work():
            cfg = self.build_cfg()
            cfg.webhook = url
            sender = monitor.DiscordSender(cfg)
            embed = monitor.build_info_embed(
                "Test połączenia",
                f"Aplikacja **{APP_TITLE}** poprawnie łączy się z tym kanałem.\n"
                "Od teraz będą tu trafiać powiadomienia o zmianach w bazie ISO.", cfg)
            ok = sender.send_embeds([embed])
            self._post("done_test", ok)

        threading.Thread(target=work, daemon=True).start()

    def _on_test_done(self, ok: bool) -> None:
        if ok:
            self.settings_status.configure(text="Wiadomość testowa wysłana — sprawdź Discorda.",
                                           text_color=COLORS["NEW"])
            self.append_log("Wiadomość testowa wysłana na Discord.")
        else:
            self.settings_status.configure(
                text="Nie udało się wysłać — sprawdź adres webhooka (szczegóły w Dzienniku).",
                text_color=COLORS["WITHDRAWN"])

    # --------------------------------------------------------- harmonogram

    def _schedule_next_check(self) -> None:
        try:
            hours = max(1, int(self.settings["interval_hours"]))
        except (ValueError, TypeError):
            hours = 4
        self.next_check_at = time.time() + hours * 3600

    def _update_next_label(self) -> None:
        self._update_discord_label()
        if self.busy or not self.next_check_at:
            self.next_label.configure(text="Sprawdzanie w toku…" if self.busy else "")
            return
        remaining = int(self.next_check_at - time.time())
        if remaining <= 0:
            self.start_check(reason="harmonogram")
            return
        hours, rest = divmod(remaining, 3600)
        minutes = rest // 60
        self.next_label.configure(
            text=f"Następne sprawdzenie za {hours} h {minutes:02d} min"
            if hours else f"Następne sprawdzenie za {minutes} min")

    def _update_discord_label(self) -> None:
        has_hook = bool(str(self.settings.get("webhook", "")).strip())
        on = bool(self.settings.get("send_to_discord"))
        if has_hook and on:
            self.discord_label.configure(text="Discord: podłączony", text_color=COLORS["NEW"])
        elif has_hook:
            self.discord_label.configure(text="Discord: wyłączony", text_color=COLORS["STAGE"])
        else:
            self.discord_label.configure(text="Discord: brak webhooka",
                                         text_color=("gray45", "gray60"))

    def _restore_last_state(self) -> None:
        try:
            meta = monitor.load_meta(app_dir() / "state" / "meta.json")
        except Exception:
            meta = {}
        if meta.get("rows"):
            self.stat_widgets["rows"].configure(
                text=f"{int(meta['rows']):,}".replace(",", " "))
        if meta.get("last_run"):
            try:
                stamp = datetime.fromisoformat(meta["last_run"])
                self.stat_widgets["last"].configure(text=stamp.strftime("%d.%m.%Y %H:%M"))
            except ValueError:
                pass
        if meta.get("last_changes") is not None:
            self.stat_widgets["found"].configure(text=str(meta["last_changes"]))
        self._update_discord_label()

    # ------------------------------------------------------------- zasobnik

    def _tray_image(self) -> Image.Image:
        try:
            return Image.open(resource_path("ikona.png")).convert("RGBA").resize((64, 64))
        except Exception:
            return Image.new("RGBA", (64, 64), (31, 106, 165, 255))

    def _start_tray(self) -> None:
        try:
            menu = pystray.Menu(
                pystray.MenuItem("Pokaż okno", self._tray_show, default=True),
                pystray.MenuItem("Sprawdź teraz", self._tray_check),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Zakończ", self._tray_quit),
            )
            self.tray = pystray.Icon("iso_monitor", self._tray_image(), APP_TITLE, menu)
            threading.Thread(target=self.tray.run, daemon=True).start()
        except Exception as exc:                                     # noqa: BLE001
            self.append_log(f"Nie udało się utworzyć ikony w zasobniku: {exc}")
            self.tray = None

    def _notify_tray(self, text: str) -> None:
        try:
            if self.tray and self.tray.HAS_NOTIFICATION:
                self.tray.notify(text, APP_TITLE)
        except Exception:
            pass

    def _tray_show(self, *_args) -> None:
        self.after(0, self._show_window)

    def _tray_check(self, *_args) -> None:
        self.after(0, lambda: self.start_check(reason="zasobnik"))

    def _tray_quit(self, *_args) -> None:
        self.after(0, self.quit_app)

    def _show_window(self) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()

    def hide_to_tray(self) -> None:
        if self.tray:
            self.withdraw()
            self._notify_tray("Aplikacja działa dalej w tle.")
        else:
            self.iconify()

    def on_close(self) -> None:
        if self.settings.get("minimize_to_tray") and self.tray:
            self.hide_to_tray()
        else:
            self.quit_app()

    def quit_app(self) -> None:
        try:
            if self.tray:
                self.tray.stop()
        except Exception:
            pass
        self.destroy()


# --------------------------------------------------------------------------
# Start
# --------------------------------------------------------------------------


def selftest() -> int:
    """Buduje okno, przemiela pętlę zdarzeń i zamyka — do testu bez klikania."""
    app = IsoMonitorApp(selftest=True)
    app.append_log("Tryb testowy: sprawdzam, czy interfejs buduje się bez błędów.")
    app.update_idletasks()
    for _ in range(40):
        app.update()
        time.sleep(0.02)
    widgets = len(app.winfo_children())
    app.destroy()
    print(f"SELFTEST OK — okno zbudowane, elementów najwyzszego poziomu: {widgets}")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    app = IsoMonitorApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
