# Music-Sync — Implementierungsplan

> CLI-Tool, das einen lokalen Musik-Ordner analysiert und fehlende Songs der dort vorhandenen Künstler von **YouTube Music** (mit YouTube als Fallback) herunterlädt.

---

## 1. Projektziel

Ein Python-CLI-Tool, das:

1. einen bestehenden lokalen Musik-Ordner scannt und die enthaltenen Künstler/Songs erfasst,
2. pro Künstler die komplette Diskografie auf YouTube Music abruft,
3. fehlende Songs identifiziert (Fuzzy-Match gegen lokale Bibliothek),
4. diese als `.opus` mit korrekten Metadaten und Cover Art herunterlädt,
5. sich für manuelle Nutzung **und** automatisierte cron-Läufe eignet.

---

## 2. Tech-Stack

| Komponente | Library | Zweck |
|------------|---------|-------|
| Sprache | Python 3.11+ | — |
| YT Music API | `ytmusicapi` | Künstler-Diskografie, Alben, Tracks |
| Download | `yt-dlp` | Audio-Download von YT/YT Music |
| Tags | `mutagen` | Lesen lokaler Tags, Schreiben in `.opus` |
| CLI | `click` | Befehlsstruktur |
| Terminal-UI | `rich` | Tabellen, Progress-Bars |
| Config | `PyYAML` | `config.yaml` parsen |
| Fuzzy-Match | `rapidfuzz` | Duplikat-Erkennung |
| State | `sqlite3` (stdlib) | Cache & Audit-Trail |

---

## 3. Feature-Spezifikation

### Kern-Funktionalität

| # | Aspekt | Entscheidung |
|---|--------|-------------|
| 1 | Interface | CLI |
| 2 | Künstler-Liste | Auto-erkannt aus lokalem Musik-Ordner |
| 3 | Primärquelle | YouTube Music |
| 4 | Sekundärquelle | Regulärer YouTube-Kanal (per Künstler in Config wählbar) |
| 5 | Künstler-ID | Manuell in `config.yaml` eingetragen (YT Music Browse-ID oder YT Channel-URL) |
| 6 | Download-Scope | Nur fehlende Songs (Gap-Filling) |
| 7 | Duplikat-Check | Fuzzy-Matching auf Künstler + Titel (Schwelle konfigurierbar) |
| 8 | Filter | Studio-Only — Live/Remix/Cover/Demo/Acoustic/Instrumental/Karaoke werden übersprungen |

### Datei-Handling

| # | Aspekt | Entscheidung |
|---|--------|-------------|
| 9 | Audio-Format | `.opus` (kein Re-Encoding — YT streamt nativ in Opus) |
| 10 | Qualität | Beste verfügbare (256kbps mit YT Music Premium) |
| 11 | Dateischema | `Künstler/Album/01 - Titel.opus` |
| 12 | Fallback ohne Album | `Künstler/Singles/Titel.opus` |
| 13 | Cover Art | YT Music Album-Cover embedded |
| 14 | Filename-Sanitization | Umlaute & normale Zeichen bleiben — nur `/ : ? * " < > \|` werden zu `_` |
| 15 | Metadaten-Quelle | YT Music direkt (saubere Daten, kein MusicBrainz nötig) |

### Persistenz & Logging

| # | Aspekt | Entscheidung |
|---|--------|-------------|
| 16 | State | SQLite-Datenbank: `~/.cache/music-sync/state.db` |
| 17 | Logging | Datei mit Rotation: `~/.cache/music-sync/music-sync.log` (10 MB, 5 Archive) |
| 18 | Config-Ort | `/mnt/code/music-sync/config.yaml` |
| 19 | Cookies | Optionale Cookie-Datei in Config (für YT Music Premium 256kbps) |

### Betrieb

| # | Aspekt | Entscheidung |
|---|--------|-------------|
| 20 | First-Run | Interaktiver Wizard fragt nach Musik-/Zielordner und ersten Künstlern |
| 21 | Automatisierung | Manuelle Ausführung + Beispiel-cronjob in README |
| 22 | Dry-Run | `--dry-run` Flag zeigt geplante Downloads ohne sie auszuführen |
| 23 | Retry-Logik | 3 Versuche pro Download, danach in DB als `failed` markiert |
| 24 | Bandbreite | Unbegrenzt |
| 25 | Disk-Space | Min-Free-Space-Check (Default 500 MB, konfigurierbar) |
| 26 | Parallelität | Sequentiell (ein Download nach dem anderen) |
| 27 | Verifizierung | Keine extra Checks (Vertrauen auf yt-dlp) |

---

## 4. Datenbank-Schema (SQLite)

```sql
CREATE TABLE downloads (
    id INTEGER PRIMARY KEY,
    video_id TEXT NOT NULL UNIQUE,
    artist TEXT NOT NULL,
    title TEXT NOT NULL,
    album TEXT,
    file_path TEXT,
    status TEXT NOT NULL,  -- 'success' | 'failed' | 'skipped'
    retry_count INTEGER DEFAULT 0,
    error_message TEXT,
    downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE channel_state (
    artist TEXT PRIMARY KEY,
    source TEXT NOT NULL,        -- 'ytmusic' | 'youtube'
    source_id TEXT NOT NULL,
    last_sync TIMESTAMP,
    last_known_release TEXT
);

CREATE INDEX idx_artist ON downloads(artist);
CREATE INDEX idx_status ON downloads(status);
```

---

## 5. Beispiel `config.yaml`

```yaml
# Pfade
music_dir: /home/johncena/Musik
download_dir: /home/johncena/Musik
cookies_file: /home/johncena/.config/music-sync/cookies.txt   # optional, für Premium

# Verhalten
min_free_space_mb: 500
fuzzy_match_threshold: 85
log_level: INFO

# Filter-Keywords (Songs mit diesen Substrings im Titel werden übersprungen)
filter_keywords:
  - "(Live)"
  - "(Acoustic)"
  - "(Remix)"
  - "(Cover)"
  - "(Demo)"
  - "(Instrumental)"
  - "(Karaoke)"

# Künstler-Mapping
artists:
  - name: "Rammstein"
    ytmusic_id: "UCw39ZmFGboKvrHv4n6LviCA"

  - name: "Linkin Park"
    ytmusic_id: "MPADUC8KHpiCNbHhBznKtb1iE0bA"

  - name: "Indie Band X"
    youtube_url: "https://youtube.com/@indiebandx"   # Fallback wenn nicht auf YT Music
```

---

## 6. CLI-Befehle

```bash
music-sync init              # Interaktiver Wizard (First-Run)
music-sync scan              # Lokale Bibliothek analysieren & Übersicht
music-sync sync              # Neue Songs aller Künstler herunterladen
music-sync sync --artist X   # Nur ein Künstler
music-sync sync --dry-run    # Vorschau ohne Download
music-sync list-missing      # Welche Songs würden geladen?
music-sync retry-failed      # Fehlgeschlagene Downloads erneut versuchen
```

---

## 7. Projektstruktur

```
music-sync/
├── music_sync/
│   ├── __init__.py
│   ├── cli.py                  # Click-basierte CLI-Befehle
│   ├── config.py               # YAML-Loader + Validation
│   ├── wizard.py               # Interaktiver First-Run Setup
│   ├── scanner.py              # Lokale Bibliothek scannen (mutagen)
│   ├── matcher.py              # Fuzzy-Matching (rapidfuzz)
│   ├── source_ytmusic.py       # YT Music Browsing (ytmusicapi)
│   ├── source_youtube.py       # YT Channel Fallback (yt-dlp)
│   ├── downloader.py           # yt-dlp Wrapper für Audio-Download
│   ├── tagger.py               # Tags + Cover Art einbetten
│   ├── db.py                   # SQLite-Zugriff
│   ├── logger.py               # Rotating File Logger
│   └── filters.py              # Studio-Filter + Filename-Sanitization
├── config.example.yaml
├── requirements.txt
├── README.md
├── PLAN.md                     # Dieses Dokument
└── tests/
    ├── test_scanner.py
    ├── test_matcher.py
    ├── test_filters.py
    └── test_tagger.py
```

---

## 8. Implementierungs-Phasen

### Phase 1 — Grundgerüst (~1 h)
- Projektstruktur anlegen
- `requirements.txt` + `pyproject.toml`
- `config.py` mit YAML-Loading und Validation
- `logger.py` mit Rotating File Handler
- Basis-CLI-Skelett (`cli.py`)

### Phase 2 — Scanner & Matcher (~1.5 h)
- `scanner.py`: lokale Musik scannen (rekursiv), Tags via `mutagen` lesen
- Fallback: Dateinamen parsen (`Künstler - Titel.ext`)
- `matcher.py`: Fuzzy-Matching mit `rapidfuzz`
- `filters.py`: Filename-Sanitization
- Tests für Scanner + Matcher

### Phase 3 — YT Music Integration (~1.5 h)
- `source_ytmusic.py`: `ytmusicapi` einbinden
- Künstler-Diskografie abrufen (Alben + Singles)
- Studio-Filter anwenden
- Track-Liste mit Metadaten zurückgeben

### Phase 4 — Downloader + Tagger (~1.5 h)
- `downloader.py`: `yt-dlp`-Wrapper, Opus, 256kbps, Cookie-Support
- `tagger.py`: Tags ins `.opus` schreiben, Cover Art einbetten
- Disk-Space-Check vor Download
- Retry-Logik (3 Versuche)

### Phase 5 — State-DB + Sync-Logik (~1 h)
- `db.py`: SQLite-Initialisierung + Queries
- Sync-Pipeline: scan → fetch → match → download → tag → mark
- Failed-State tracken

### Phase 6 — CLI-Vervollständigung & Wizard (~1 h)
- Alle CLI-Befehle implementieren
- `wizard.py` für First-Run
- `--dry-run` Modus
- `rich`-basierte Progress-Bars

### Phase 7 — Fallback & Polish (~1 h)
- `source_youtube.py` für YT-Channel Fallback
- README mit Setup-Anleitung
- Beispiel-cronjob
- End-to-End Test mit echtem Künstler

**Geschätzter Gesamtaufwand: ~8 h**

---

## 9. Risiken & Mitigationen

| Risiko | Schwere | Mitigation |
|--------|---------|------------|
| `ytmusicapi` benötigt Auth-Setup (`oauth.json`) | MITTEL | Wizard generiert Auth-Anweisungen, einmaliges Setup |
| YT-Music API ändert sich (inoffiziell) | MITTEL | `ytmusicapi` ist aktiv gewartet, Auto-Update als Empfehlung im README |
| Fuzzy-Match liefert False Positives (Song falsch als "vorhanden" erkannt) | MITTEL | Schwellwert konfigurierbar (Default 85), `list-missing` zum manuellen Review |
| Künstler nicht auf YT Music verfügbar | NIEDRIG | Fallback auf regulären YT-Kanal pro Künstler in Config |
| YT-Rate-Limit / IP-Block | NIEDRIG | Sequentielle Downloads, Retry mit Backoff |
| Falsche/fehlende Album-Info | NIEDRIG | Fallback in `Singles/` Ordner |
| Copyright-Sperren in Region | NIEDRIG | Logging, kein Crash — wird übersprungen |

---

## 10. Out of Scope (V1)

Diese Features sind bewusst **nicht** im ersten Wurf enthalten:

- Spotify / Deezer / Apple Music als Quellen
- Web-UI oder Desktop-GUI
- Automatisches Library-Sync (eigene YT Music Bibliothek)
- MusicBrainz-Integration
- Audio-Fingerprinting (acoustid)
- Parallele Downloads
- Bandbreiten-Limit
- Track-Length-Verifizierung
- Lyrics-Embedding

Können in späteren Versionen ergänzt werden.

---

## 11. Nächste Schritte

1. Bestätigung dieses Plans durch den User
2. Implementierung gemäß Phasen 1–7
3. End-to-End-Test mit echten Künstlern aus der vorhandenen Bibliothek
4. README + cronjob-Beispiel
5. Optional: erste Erweiterungen aus "Out of Scope" basierend auf Praxiserfahrung
