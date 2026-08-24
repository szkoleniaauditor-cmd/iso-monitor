# 🌍 ISO Nowości — monitor nowych i zmienionych norm ISO

Aplikacja codziennie (co 4 godziny) pobiera oficjalny plik z **ISO Open Data**, porównuje go
z poprzednim pobraniem i wysyła na **Discord** powiadomienie o każdej wykrytej zmianie —
z ikonką typu zmiany, numerem i tytułem normy, datą publikacji, komitetem technicznym
oraz klikalnym linkiem do strony normy na `iso.org`.

Działa w całości na **GitHub Actions** — nie potrzebujesz własnego serwera ani włączonego komputera.

---

## 📋 Spis treści

- [Co monitoruje](#-co-monitoruje)
- [Jak wygląda powiadomienie](#-jak-wygląda-powiadomienie)
- [Codzienny raport o 21:00](#-codzienny-raport-o-2100)
- [Pliki w projekcie](#-pliki-w-projekcie)
- [Wdrożenie krok po kroku](#-wdrożenie-krok-po-kroku)
- [Wersja okienkowa na Windows](#️-wersja-okienkowa-na-windows)
- [Konfiguracja](#️-konfiguracja)
- [Uruchomienie lokalne](#-uruchomienie-lokalne)
- [Jak działa wykrywanie zmian](#-jak-działa-wykrywanie-zmian)
- [Rozwiązywanie problemów](#-rozwiązywanie-problemów)
- [Uwagi i limity](#️-uwagi-i-limity)

---

## 🔍 Co monitoruje

| Ikona | Typ zmiany | Kiedy się pojawia |
|:-----:|------------|-------------------|
| 🆕 | **Nowa norma** | W bazie pojawia się nowa pozycja, albo norma (wydanie 1) osiąga etap `60.60` — czyli została opublikowana |
| 🔄 | **Rewizja / nowe wydanie** | Rośnie numer wydania, zmienia się data publikacji, publikowane jest kolejne wydanie normy, albo pojawia się nowy projekt zastępujący istniejącą normę |
| ⛔ | **Wycofanie normy** | Norma przechodzi do etapu `95.xx` (wycofana) lub znika z bazy ISO |
| ⏳ | **Zmiana etapu DIS/FDIS** | Projekt wchodzi w etap `40.xx` (DIS — ankieta publiczna) lub `50.xx` (FDIS — końcowe zatwierdzenie) |

Baza ISO Open Data zawiera obecnie **ponad 81 000 pozycji** — norm, specyfikacji technicznych,
raportów technicznych i projektów na wszystkich etapach opracowania.

---

## 💬 Jak wygląda powiadomienie

Każda zmiana to osobna karta (embed) na Discordzie:

```
┌────────────────────────────────────────────────────────┐
│ 🆕 ISO 9001:2026                          ← klikalny   │
│                                                        │
│ Quality management systems — Requirements              │
│ Norma została opublikowana                             │
│ 🔗 Zobacz na iso.org                                   │
│                                                        │
│ 📅 Data publikacji     🏛 Komitet techniczny           │
│ 2026-08-15             ISO/TC 176/SC 2                 │
│                                                        │
│ 📊 Etap                                                │
│ 50.60 Zakończenie głosowania nad FDIS                  │
│   ↓                                                    │
│ 60.60 Norma Międzynarodowa opublikowana                │
│                                                        │
│ Nowa norma • Norma Międzynarodowa (IS) • wydanie 6     │
└────────────────────────────────────────────────────────┘
```

Kolor lewej krawędzi zależy od typu zmiany: 🟢 nowa, 🔵 rewizja, 🔴 wycofanie, 🟠 zmiana etapu.
Tytuł karty oraz link „🔗 Zobacz na iso.org" prowadzą do `https://www.iso.org/standard/{id}.html`.

Plik **`ikona.png`** jest używany jako **avatar bota** przy każdej wiadomości na Discordzie.

---

## 📅 Codzienny raport o 21:00

Poza powiadomieniami na bieżąco raz dziennie przychodzi zbiorcze sprawozdanie z całej doby —
**zwykła wiadomość tekstowa, nie karta embed**, żeby mieściła się w limicie 2000 znaków
konta bez Nitro:

```
📋 RAPORT ISO | Poniedziałek 24.08.2026
━━━━━━━━━━━━━━━━━━━━
📊 Sprawdzono: 81 323 norm
🔔 Zmian dzisiaj: 6
   🆕 1   🔄 1   ⛔ 1   ⏳ 3

🆕 ISO/IEC 9593-1:1990/Amd 1:1995 - Information processing systems…
🔄 ISO 2110:1989/Amd 1:1991 - Information technology — Data communication…
⛔ ISO/R 102:1959 - wycofana
⏳ ISO/DIS 14060 - Net zero aligned organizations
⏳ ISO/DIS 19186-1 - Geographic information — GeoSPARQL — Part 1:…
⏳ ISO/FDIS 37194 - Smart community infrastructures — Disaster ri…

⏰ Następne sprawdzenie: dziś o 23:00
━━━━━━━━━━━━━━━━━━━━
```

Gdy nic się nie wydarzyło, raport jest krótki: **„😴 ISO spokojne — brak nowości."**

Jeśli zmian jest tak dużo, że lista nie mieści się w limicie, raport pokazuje ich tyle,
ile wejdzie, i kończy dopiskiem `…i N więcej` — wiadomość nigdy nie przekroczy 2000 znaków.

**Jak liczone jest „dzisiaj".** Raport nie czyta historii (monitor jej nie prowadzi — plik stanu
to migawka bazy bez znaczników czasu). Zamiast tego trzyma **własny punkt odniesienia**
w `state/raport_snapshot.csv` i porównuje z nim aktualny stan bazy ISO. Dzięki temu obejmuje
dokładnie okres od poprzedniego raportu i działa niezależnie od tego, ile razy monitor się wykonał.

**Godzina.** Cron w GitHub Actions zna wyłącznie UTC i nie uwzględnia zmiany czasu, dlatego
w harmonogramie są dwa wpisy — `0 19 * * *` (czas letni) i `0 20 * * *` (zimowy) — a zadanie
sprawdza realną godzinę w Warszawie i kończy się bez wysyłki, jeśli akurat nie jest 21:00.
Raport przychodzi więc o 21:00 czasu polskiego przez cały rok.

Raport można też wysłać ręcznie o dowolnej porze: **Actions → Monitor ISO → Run workflow**,
zaznaczając opcję **„Wyslij raport dzienny"**.

---

## 📁 Pliki w projekcie

```
ISO NOWOSCI/
├── monitor.py                    # cała logika: pobieranie, porównanie, wysyłka
├── raport.py                     # codzienne sprawozdanie na Discord (21:00)
├── app.py                        # wersja okienkowa na Windows (nakładka na monitor.py)
├── utworz_skrot.py               # tworzy skrót „ISO Monitor” na pulpicie
├── requirements.txt              # zależność wersji serwerowej: requests
├── requirements-app.txt          # zależności wersji okienkowej + budowania .exe
├── ikona.png                     # ikona aplikacji (avatar bota, ikona okna i skrótu)
├── ikona.ico                     # ta sama ikona w formacie wymaganym przez Windows
├── README.md                     # ten plik
├── .gitignore                    # pilnuje, by 60 MB CSV nie trafiło do repozytorium
├── .github/
│   └── workflows/
│       └── monitor.yml           # harmonogram GitHub Actions (monitor + raport)
├── state/                        # ← tworzone automatycznie, commitowane do repo
│   ├── iso_snapshot.csv          #   stan poprzedniego pobrania (~3 MB)
│   └── meta.json                 #   ETag, data ostatniego przebiegu, liczba rekordów
├── data/                         # ← pobrany CSV (~60 MB), NIE trafia do repozytorium
└── dist/                         # ← zbudowany „ISO Monitor.exe” (nie trafia do repo)
```

Aplikacja ma **dwa niezależne tryby pracy** — możesz używać jednego albo obu naraz:

| | Wersja serwerowa | Wersja okienkowa |
|---|---|---|
| Plik | `monitor.py` | `app.py` |
| Gdzie działa | GitHub Actions (w chmurze) | Twój komputer z Windows |
| Kiedy sprawdza | co 4 godziny, zawsze | gdy aplikacja jest uruchomiona |
| Raport dzienny | tak, o 21:00 | nie |
| Komputer musi być włączony | nie | tak |
| Powiadomienia | Discord | Discord + lista w oknie |

Oba tryby korzystają z tej samej logiki wykrywania zmian, ale **trzymają własny, osobny stan** —
serwerowa w `state/` w repozytorium, okienkowa w `%APPDATA%\ISO Monitor\`.

---

## 🚀 Wdrożenie krok po kroku

### Krok 1 — Utwórz webhook na Discordzie

1. Otwórz Discorda i przejdź na serwer, na którym chcesz dostawać powiadomienia.
2. Kliknij prawym przyciskiem na kanał (np. `#normy-iso`) → **Edytuj kanał**.
3. Zakładka **Integracje** → **Webhooki** → **Nowy webhook**.
4. Nazwij go dowolnie (nazwę i tak nadpisuje aplikacja) i kliknij **Kopiuj URL webhooka**.
5. Zachowaj skopiowany adres — wygląda tak:

```
https://discord.com/api/webhooks/1234567890/AbCdEf...
```

> ⚠️ **Ten adres to hasło.** Każdy, kto go zna, może pisać na Twoim kanale.
> Nigdy nie wklejaj go do pliku w repozytorium — w kroku 3 dodasz go jako zaszyfrowany sekret.

---

### Krok 2 — Wrzuć pliki do repozytorium GitHub

**Wariant A — przez stronę GitHub (bez instalowania czegokolwiek)**

1. Wejdź na [github.com/new](https://github.com/new).
2. Nazwa repozytorium: np. `iso-nowosci`. Wybierz **Public** (zalecane — patrz [Uwagi](#️-uwagi-i-limity)).
3. Kliknij **Create repository**.
4. Na stronie repozytorium: **Add file** → **Upload files**.
5. Przeciągnij pliki: `monitor.py`, `requirements.txt`, `README.md`, `.gitignore`, `ikona.png`.
6. Folder `.github/workflows` utwórz osobno: **Add file** → **Create new file**,
   w polu nazwy wpisz dokładnie `.github/workflows/monitor.yml` (ukośniki same utworzą foldery),
   wklej zawartość pliku i kliknij **Commit changes**.

**Wariant B — przez git (szybciej)**

W folderze z plikami uruchom:

```bash
git init
git add .
git commit -m "ISO Nowosci - monitor norm ISO"
git branch -M main
git remote add origin https://github.com/TWOJA-NAZWA/iso-nowosci.git
git push -u origin main
```

Podmień `TWOJA-NAZWA` na swoją nazwę użytkownika GitHub.

---

### Krok 3 — Dodaj Webhook URL jako GitHub Secret

To najważniejszy krok — bez niego aplikacja nie ma gdzie wysyłać powiadomień.

1. W repozytorium wejdź w **Settings** (zakładka na górze).
2. W menu po lewej: **Secrets and variables** → **Actions**.
3. Kliknij zielony przycisk **New repository secret**.
4. Wypełnij:

   | Pole | Wartość |
   |------|---------|
   | **Name** | `DISCORD_WEBHOOK_URL` |
   | **Secret** | wklej cały adres webhooka z kroku 1 |

5. Kliknij **Add secret**.

> ✅ Nazwa musi brzmieć dokładnie `DISCORD_WEBHOOK_URL` — wielkimi literami, z podkreśleniami.
> Po zapisaniu GitHub nie pokaże już wartości; można ją tylko nadpisać.

---

### Krok 4 — Włącz zapis dla GitHub Actions

Aplikacja zapisuje stan poprzedniego pobrania z powrotem do repozytorium, więc workflow
potrzebuje prawa zapisu.

1. **Settings** → **Actions** → **General**.
2. Zjedź na dół do sekcji **Workflow permissions**.
3. Zaznacz **Read and write permissions**.
4. Kliknij **Save**.

---

### Krok 5 — Pierwsze uruchomienie (stan bazowy)

Pierwszy przebieg **nie wysyła powiadomień o zmianach** — zapisuje tylko stan wyjściowy
(inaczej dostałabyś 81 000 wiadomości). Dostaniesz jedną wiadomość potwierdzającą start.

1. Wejdź w zakładkę **Actions**.
2. Jeśli zobaczysz komunikat o wyłączonych workflow — kliknij
   **I understand my workflows, go ahead and enable them**.
3. Z listy po lewej wybierz **Monitor ISO**.
4. Kliknij **Run workflow** → **Run workflow** (zielony przycisk).
5. Poczekaj 1–2 minuty i odśwież stronę.

Po zakończeniu:
- na Discordzie pojawi się wiadomość „ℹ Monitor ISO uruchomiony — zapisano stan bazowy",
- w repozytorium pojawi się folder `state/` z plikami `iso_snapshot.csv` i `meta.json`.

---

### Krok 6 — Gotowe

Od tej chwili workflow uruchamia się **automatycznie co 4 godziny**
(o 01:00, 05:00, 09:00, 13:00, 17:00 i 21:00 czasu UTC) i wysyła powiadomienia
wyłącznie o rzeczywistych zmianach. Dodatkowo **codziennie o 21:00 czasu polskiego**
przychodzi zbiorcze sprawozdanie z całej doby.

Historię przebiegów i podsumowanie każdego z nich znajdziesz w zakładce **Actions**.

---

## 🖥️ Wersja okienkowa na Windows

Jeśli wolisz mieć program na własnym komputerze, zamiast (albo obok) wersji w chmurze.

### Uruchomienie ze źródeł

```bash
pip install -r requirements-app.txt
python app.py
```

### Zbudowanie pliku .exe

```bash
pyinstaller --onefile --windowed --icon=ikona.png --name="ISO Monitor" --add-data "ikona.png;." --add-data "ikona.ico;." app.py
```

Gotowy program pojawi się w `dist\ISO Monitor.exe` (ok. 36 MB, nie wymaga zainstalowanego Pythona).

> Flagi `--add-data` są konieczne — bez nich `--onefile` nie spakuje ikony do środka
> i aplikacja uruchomi się bez logo w nagłówku oraz bez ikony w pasku tytułu.

### Skrót na pulpicie

```bash
python utworz_skrot.py
```

Tworzy skrót **ISO Monitor** na pulpicie, wskazujący na zbudowany `.exe`, z ikoną z `ikona.png`.
Skrypt sam konwertuje PNG na ICO, bo Windows nie przyjmuje plików PNG jako ikon skrótów.

### Co potrafi okno

- **Zmiany** — lista wykrytych zmian jako karty z kolorowym oznaczeniem typu
  (zielony = nowa, niebieski = rewizja, czerwony = wycofanie, pomarańczowy = DIS/FDIS),
  z tytułem, komitetem, datą, etapem i przyciskiem otwierającym normę na `iso.org`.
- **Dziennik** — przebieg pobierania i analizy, przydatny gdy coś nie działa.
- **Ustawienia** — webhook Discorda (z przyciskiem „Wyślij test”), częstotliwość sprawdzania,
  filtry komitetów i słów kluczowych, limit powiadomień.
- **Zasobnik systemowy** — zamknięcie okna chowa program obok zegarka; działa dalej w tle
  i sprawdza bazę co zadaną liczbę godzin. Prawy klik na ikonie → „Pokaż okno”,
  „Sprawdź teraz”, „Zakończ”.

Ustawienia, stan i log techniczny trafiają do `%APPDATA%\ISO Monitor\`.
Wersja okienkowa ma własny stan, niezależny od tego w repozytorium.

---

## ⚙️ Konfiguracja

Wszystkie ustawienia zmienia się w pliku `.github/workflows/monitor.yml`,
w sekcji `env:` kroku **Uruchom monitor**.

| Zmienna | Domyślnie | Opis |
|---------|-----------|------|
| `DISCORD_WEBHOOK_URL` | *(wymagana)* | Adres webhooka Discord. Ustawiana z GitHub Secret. |
| `DISCORD_USERNAME` | `ISO Nowości` | Nazwa wyświetlana przy wiadomościach. |
| `MAX_MESSAGES` | `250` | Maksymalna liczba powiadomień na jeden przebieg. Chroni przed zalaniem kanału, gdy ISO zrobi masową aktualizację. `0` = bez limitu. |
| `STAGE_WATCH_PREFIXES` | `40,50` | Etapy zgłaszane jako ⏳. `40` = DIS, `50` = FDIS. Dodaj `60`, żeby dostawać też sygnał „norma w trakcie publikacji". |
| `IGNORE_DELETED_PROJECTS` | `true` | Pomija projekty porzucone (podetap `.98`) — to zwykle szum. |
| `NOTIFY_ALL_STAGE_CHANGES` | `false` | `true` = zgłaszaj **każdą** zmianę etapu, nie tylko DIS/FDIS. Uwaga: bardzo dużo wiadomości. |
| `FILTER_COMMITTEES` | *(puste)* | Lista komitetów po przecinku, np. `ISO/TC 176,ISO/IEC JTC 1/SC 27`. Dopasowanie po początku nazwy, więc `ISO/TC 34` obejmie też `ISO/TC 34/SC 5`. Puste = wszystkie. |
| `FILTER_TYPES` | *(puste)* | Typy dokumentów, np. `IS,TS,TR`. Puste = wszystkie. |
| `FILTER_KEYWORDS` | *(puste)* | Słowa kluczowe w tytule lub numerze, np. `security,quality`. Puste = bez filtra. |
| `ICON_URL` | auto | Adres avatara bota. Domyślnie sam składa link do `ikona.png` w Twoim repozytorium. |
| `ISO_CSV_URL` | adres ISO | Źródłowy plik CSV — zmieniaj tylko, jeśli ISO przeniesie plik. |

**Przykład — tylko normy bezpieczeństwa informacji:**

```yaml
env:
  DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}
  FILTER_COMMITTEES: 'ISO/IEC JTC 1/SC 27'
```

**Zmiana częstotliwości** — sekcja `schedule` w `monitor.yml`:

```yaml
    - cron: '0 1,5,9,13,17,21 * * *'   # co 4 godziny (domyślnie)
    # - cron: '0 6 * * *'    # raz dziennie o 06:00 UTC
    # - cron: '0 * * * *'    # co godzinę
```

---

## 💻 Uruchomienie lokalne

Przydatne do testów, zanim wypchniesz cokolwiek na GitHub.

```bash
pip install -r requirements.txt
```

Podgląd zmian **bez wysyłania** i **bez zapisywania stanu**:

```bash
python monitor.py --dry-run
```

Zapis stanu bazowego (bez powiadomień):

```bash
python monitor.py --baseline
```

Normalny przebieg z wysyłką — najpierw ustaw zmienną środowiskową:

```bash
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
python monitor.py
```

W PowerShell na Windows:

```powershell
$env:DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/..."
python monitor.py
```

**Wszystkie przełączniki:**

| Przełącznik | Działanie |
|-------------|-----------|
| `--dry-run` | Nie wysyła nic i nie zapisuje stanu — tylko wypisuje, co by wysłało |
| `--baseline` | Zapisuje stan bazowy bez powiadomień o zmianach |
| `--force` | Pobiera CSV nawet jeśli się nie zmienił (ignoruje ETag) |
| `--csv PLIK` | Używa lokalnego pliku CSV zamiast pobierania |
| `--limit N` | Maksymalna liczba powiadomień w tym przebiegu |
| `--state-dir KAT` | Inny katalog stanu (domyślnie `./state`) |
| `--data-dir KAT` | Inny katalog na pobrany CSV (domyślnie `./data`) |
| `--save-state` | Zapisz stan mimo `--dry-run` |

---

## 🔬 Jak działa wykrywanie zmian

**1. Pobranie.** Aplikacja wysyła zapytanie warunkowe z nagłówkiem `If-None-Match`.
Jeśli ISO odpowie `304 Not Modified`, przebieg kończy się natychmiast — bez pobierania 60 MB.

**2. Porównanie.** Z pliku CSV brane są tylko pola potrzebne do porównania:
`id`, `reference`, `currentStage`, `edition`, `publicationDate`. Zapisywane są w
`state/iso_snapshot.csv` (~3 MB) — dzięki temu repozytorium nie puchnie,
a git skutecznie kompresuje kolejne wersje posortowanego pliku tekstowego.

**3. Klasyfikacja.** Dla każdej pozycji zgłaszane jest **co najwyżej jedno**, najistotniejsze
zdarzenie — nie dostaniesz czterech wiadomości o tej samej normie:

```
nowe id w bazie ──┬── ma wypełnione „replaces"  → 🔄 rewizja
                  └── nie ma                    → 🆕 nowa norma

zmiana etapu ─────┬── na 95.xx                  → ⛔ wycofanie
                  ├── na 60.60, wydanie 1       → 🆕 opublikowana
                  ├── na 60.60, wydanie 2+      → 🔄 nowe wydanie
                  └── na 40.xx / 50.xx          → ⏳ DIS / FDIS

bez zmiany etapu ─┬── wzrósł numer wydania      → 🔄 rewizja
                  └── zmieniła się data publik. → 🔄 rewizja

id zniknęło z bazy                              → ⛔ wycofanie
```

**4. Wysyłka.** Discord przyjmuje maksymalnie 10 kart w jednej wiadomości, więc powiadomienia
lecą paczkami po 10. Limit szybkości (`429`) jest obsługiwany — aplikacja czeka tyle,
ile każe Discord, i ponawia próbę.

**5. Zapis stanu.** Stan zapisuje się **dopiero po udanej wysyłce**. Jeśli Discord był
niedostępny, stan zostaje nietknięty i te same zmiany zostaną zgłoszone w kolejnym przebiegu —
nic nie ginie.

### Kody etapów ISO

W CSV etapy są zapisane bez kropki (`4020` = `40.20`). Najważniejsze:

| Kod | Znaczenie |
|-----|-----------|
| `10.99` | Nowy projekt zatwierdzony |
| `20.20` | Projekt roboczy (WD) w opracowaniu |
| `30.20` | Projekt komitetu (CD) w głosowaniu |
| `40.20` | **DIS** — ankieta publiczna, 12 tygodni |
| `40.60` | Zakończenie głosowania nad DIS |
| `50.20` | **FDIS** — końcowe zatwierdzenie, 8 tygodni |
| `60.00` | Norma w trakcie publikacji |
| `60.60` | **Norma opublikowana** |
| `90.92` | Norma do zrewidowania |
| `90.93` | Norma potwierdzona (przegląd bez zmian) |
| `95.99` | **Norma wycofana** |

---

## 🔧 Rozwiązywanie problemów

| Objaw | Przyczyna | Rozwiązanie |
|-------|-----------|-------------|
| Workflow czerwony: `Brak sekretu DISCORD_WEBHOOK_URL` | Sekret nie został dodany albo ma inną nazwę | Powtórz [krok 3](#krok-3--dodaj-webhook-url-jako-github-secret). Nazwa musi brzmieć dokładnie `DISCORD_WEBHOOK_URL` |
| `webhook odrzucony (HTTP 401/403/404)` | Webhook został usunięty lub adres jest niepełny | Utwórz webhook ponownie i nadpisz sekret |
| Krok „Zapisz stan": `Permission denied` / `403` | Actions nie ma prawa zapisu | Powtórz [krok 4](#krok-4--włącz-zapis-dla-github-actions) |
| Brak jakichkolwiek wiadomości | Pierwszy przebieg zapisuje tylko stan bazowy | To normalne. Powiadomienia przyjdą przy następnej rzeczywistej zmianie w ISO |
| Wciąż cisza po kilku dniach | Możliwe filtry albo brak zmian w bazie | Sprawdź `FILTER_*` w `monitor.yml`; w Actions zobacz podsumowanie przebiegu |
| Zbyt dużo wiadomości | Zbyt szerokie kryteria | Ustaw `FILTER_COMMITTEES`, zmniejsz `MAX_MESSAGES` lub upewnij się, że `NOTIFY_ALL_STAGE_CHANGES` = `false` |
| Avatar bota się nie wyświetla | Repozytorium jest prywatne — Discord nie pobierze `ikona.png` | Ustaw repo jako publiczne albo wskaż `ICON_URL` na publiczny adres obrazka |
| Workflow przestał się uruchamiać | GitHub wyłącza harmonogramy w repozytoriach bez aktywności przez 60 dni | Wejdź w Actions i uruchom workflow ręcznie |
| `Plik CSV nie zmienił się (HTTP 304)` | ISO nie opublikowało nowej wersji pliku | To poprawne zachowanie, nie błąd |

---

## ⚠️ Uwagi i limity

- **Repozytorium publiczne vs prywatne.** Publiczne ma darmowe, nielimitowane minuty
  GitHub Actions i pozwala Discordowi pobrać `ikona.png` jako avatar. Prywatne zużywa
  darmowy limit (2000 min/mies.) — ten monitor to około 1–2 minuty na przebieg,
  czyli mniej więcej 360 minut miesięcznie. W repozytorium nie ma żadnych sekretów
  w plikach, więc publiczne jest bezpieczne.
- **Harmonogram GitHub bywa opóźniony** o kilka do kilkunastu minut przy dużym obciążeniu —
  to normalne i nie wpływa na wykrywanie zmian.
- **Czas w cronie to UTC**, nie czas polski (latem UTC+2, zimą UTC+1).
- **Plik CSV z ISO waży około 60 MB** i jest wpisany do `.gitignore` — nigdy nie trafia
  do repozytorium. Commitowany jest wyłącznie lekki snapshot z folderu `state/`.
- **Dane pochodzą z ISO Open Data** i mają charakter informacyjny. Wiążącym źródłem
  pozostaje `iso.org`.

---

## 📄 Źródło danych

```
https://isopublicstorageprod.blob.core.windows.net/opendata/_latest/iso_deliverables_metadata/csv/iso_deliverables_metadata.csv
```

Zbiór **ISO deliverables metadata** udostępniany publicznie przez ISO
w ramach [ISO Open Data](https://www.iso.org/open-data.html).
