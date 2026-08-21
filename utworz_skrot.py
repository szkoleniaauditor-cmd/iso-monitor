#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tworzy skrót „ISO Monitor" na pulpicie Windows.

Skrót wskazuje na zbudowany plik dist\\ISO Monitor.exe, a jego ikoną jest
ikona.png z folderu projektu (przekonwertowana do ikona.ico — Windows nie
przyjmuje plików PNG jako ikon skrótów).

Uruchomienie:
    python utworz_skrot.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

SHORTCUT_NAME = "ISO Monitor"
DESCRIPTION = "Monitor nowości w bazie norm ISO"


def desktop_dir() -> Path:
    """Pulpit użytkownika — z uwzględnieniem przekierowania np. na OneDrive."""
    try:
        from win32com.shell import shell, shellcon
        return Path(shell.SHGetFolderPath(0, shellcon.CSIDL_DESKTOPDIRECTORY, None, 0))
    except Exception:
        return Path.home() / "Desktop"


def ensure_ico(root: Path) -> Path:
    """Zwraca ikonę w formacie .ico, tworząc ją z ikona.png jeśli trzeba."""
    ico, png = root / "ikona.ico", root / "ikona.png"
    if ico.exists():
        return ico
    if not png.exists():
        raise FileNotFoundError("Brak pliku ikona.png w folderze projektu.")
    from PIL import Image
    Image.open(png).convert("RGBA").save(
        ico, format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"  Utworzono {ico.name} z ikona.png")
    return ico


def main() -> int:
    root = Path(__file__).resolve().parent
    exe = root / "dist" / f"{SHORTCUT_NAME}.exe"

    print("Tworzenie skrótu na pulpicie")
    print("-" * 52)

    if not exe.exists():
        print(f"BŁĄD: nie znaleziono {exe}")
        print("Zbuduj najpierw aplikację:")
        print('  pyinstaller --onefile --windowed --icon=ikona.png '
              '--name="ISO Monitor" --add-data "ikona.png;." '
              '--add-data "ikona.ico;." app.py')
        return 1
    print(f"  Plik programu: {exe}")

    icon = ensure_ico(root)
    # kopia ikony obok .exe, żeby skrót nie zależał od folderu ze źródłami
    icon_next_to_exe = exe.parent / icon.name
    if not icon_next_to_exe.exists() or icon_next_to_exe.stat().st_mtime < icon.stat().st_mtime:
        shutil.copy2(icon, icon_next_to_exe)
    print(f"  Ikona skrótu:  {icon_next_to_exe}")

    desktop = desktop_dir()
    if not desktop.exists():
        print(f"BŁĄD: nie znaleziono pulpitu ({desktop})")
        return 1
    link = desktop / f"{SHORTCUT_NAME}.lnk"
    print(f"  Pulpit:        {desktop}")

    try:
        import win32com.client
    except ImportError:
        print("BŁĄD: brak biblioteki pywin32. Zainstaluj ją poleceniem:")
        print("  pip install pywin32")
        return 1

    shell_obj = win32com.client.Dispatch("WScript.Shell")
    shortcut = shell_obj.CreateShortCut(str(link))
    shortcut.TargetPath = str(exe)
    shortcut.WorkingDirectory = str(exe.parent)
    shortcut.IconLocation = f"{icon_next_to_exe},0"
    shortcut.Description = DESCRIPTION
    shortcut.WindowStyle = 1
    shortcut.save()

    if not link.exists():
        print("BŁĄD: skrót nie został utworzony.")
        return 1

    # odczyt z powrotem — potwierdzenie, że wszystko się zapisało
    check = shell_obj.CreateShortCut(str(link))
    print("-" * 52)
    print(f"GOTOWE: {link}")
    print(f"  wskazuje na: {check.TargetPath}")
    print(f"  ikona:       {check.IconLocation}")
    print(f"  rozmiar:     {link.stat().st_size} B")
    return 0


if __name__ == "__main__":
    sys.exit(main())
