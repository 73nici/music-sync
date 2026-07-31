# Music-Sync

CLI-Tool, das einen lokalen Musik-Ordner analysiert und fehlende Songs der dort vorhandenen Künstler von **YouTube Music** (mit YouTube als Fallback) herunterlädt.

Details zur Architektur: siehe [PLAN.md](./PLAN.md).

---

## Features

- Scannt rekursiv den lokalen Musik-Ordner und liest Metadaten via `mutagen`
- Fragt YT-Music-Diskografien pro Künstler ab (`ytmusicapi`)
- Filtert Live/Remix/Cover/Demo-Versionen heraus (Studio-Only)
- Fuzzy-Matching gegen lokale Bibliothek (`rapidfuzz`) — kein doppeltes Laden
- Download als `.opus` (kein Re-Encoding) via `yt-dlp`
- Bettet Cover Art aus YT Music ein
- Ablage: `Künstler/Album/01 - Titel.opus`, Fallback `Künstler/Singles/Titel.opus`
- Adaptiver Scan-Zeitplan: nur Künstler mit frischen Releases werden häufig abgefragt
- SQLite-Statedb gegen wiederholte Versuche
- Retry-Logik (3 Versuche), `--dry-run`, rotierte Logs
- Docker-fähig für einfaches Deployment

---

## Installation (lokal)

```bash
cd /mnt/code/music-sync
python -m venv .venv
source .venv/bin/activate
pip install -e .

# ffmpeg wird benötigt (Opus-Extraktion)
sudo zypper install ffmpeg   # OpenSUSE
```

### Erstkonfiguration

```bash
music-sync init
```

Der Wizard fragt nach Musik-Ordner, Zielordner und ersten Künstlern. Die `config.yaml` wird im Projektordner abgelegt.

### Befehle

```bash
music-sync scan              # Bibliothek analysieren
music-sync sync              # Fällige Künstler prüfen und neue Songs laden
music-sync sync --artist X   # Nur einen Künstler
music-sync sync --all        # Alle Künstler prüfen (Scan-Zeitplan ignorieren)
music-sync sync --dry-run    # Vorschau ohne Download
music-sync schedule          # Wann wird welcher Künstler wieder gescannt?
music-sync list-missing      # Was würde geladen?
music-sync retry-failed      # Failed neu versuchen
```

---

## Docker-Deployment

### Build

```bash
cp .env.example .env
# .env anpassen (MUSIC_DIR, APP_UID, APP_GID)
docker compose build
```

### Erstkonfiguration im Container

```bash
docker compose run --rm music-sync init
```

Die Config wird im gemounteten `${CONFIG_DIR}` als `config.yaml` abgelegt.

### Sync ausführen

```bash
docker compose run --rm music-sync sync
docker compose run --rm music-sync sync --artist "Rammstein"
docker compose run --rm music-sync sync --dry-run
```

### Verzeichnisstruktur im Container

| Host-Pfad        | Container-Pfad | Inhalt                            |
|------------------|----------------|-----------------------------------|
| `${MUSIC_DIR}`   | `/music`       | Musikbibliothek (Quelle + Ziel)   |
| `${CONFIG_DIR}`  | `/config`      | `config.yaml`, optional `cookies.txt` |
| `${CACHE_DIR}`   | `/cache`       | SQLite-State und rotierte Logs    |

> **Hinweis:** Trage in `config.yaml` für `music_dir` und `download_dir` die **Container-Pfade** ein (`/music`), nicht die Host-Pfade.

### YT Music Premium Cookies

Cookie-Datei nach `${CONFIG_DIR}/cookies.txt` legen und in `config.yaml`:

```yaml
cookies_file: /config/cookies.txt
```

### PoT-Token-Provider

Der `bgutil`-PoT-Provider generiert echte Proof-of-Origin-Tokens und macht die yt-dlp-Requests gegenüber YouTube authentischer (weniger Rate-Limits, weniger SABR-Drosselung). Er läuft als eigener Container im docker-compose-Setup und ist im Default bereits aktiviert. In `config.yaml` muss nur die URL gesetzt sein:

```yaml
# Lokal:           http://127.0.0.1:4416
# Docker-Compose:  http://pot-provider:4416
pot_provider_url: http://pot-provider:4416
```

Für eine **lokale** (non-Docker) Installation lässt sich der Provider eigenständig starten:

```bash
docker run -d --name bgutil-provider -p 4416:4416 --restart unless-stopped \
  brainicism/bgutil-ytdlp-pot-provider
```

### Cron-Job auf dem Host

```cron
# Jede Nacht um 03:00 neue Songs synchronisieren
0 3 * * * cd /opt/music-sync && /usr/bin/docker compose run --rm music-sync sync >> /var/log/music-sync.log 2>&1
```

---

## Cron ohne Docker

```cron
0 3 * * * /home/johncena/.venvs/music-sync/bin/music-sync --config /mnt/code/music-sync/config.yaml sync
```

---

## Adaptiver Scan-Zeitplan

Ein häufiger Cron (z.B. alle 3h) muss nicht bei jedem Lauf jede Diskografie abfragen: Eine Band, deren letztes Album von 2010 ist, veröffentlicht auch in den nächsten 3 Stunden nichts. `sync` prüft deshalb pro Künstler, ob ein erneuter Scan überhaupt fällig ist, und überspringt den Rest.

Wie alt ist das neueste Release des Künstlers?

| Alter des letzten Releases | Erneuter Scan frühestens nach |
|----------------------------|-------------------------------|
| ≤ 30 Tage                  | jedem Lauf                    |
| ≤ 180 Tage                 | 12 h                          |
| ≤ 365 Tage                 | 24 h                          |
| ≤ 3 Jahre                  | 3 Tagen                       |
| älter                      | 7 Tagen                       |

Das Alter kommt aus zwei Quellen, die jüngere gewinnt:

1. **Beobachtete Änderung** — Music-Sync speichert pro Künstler einen Fingerprint der Diskografie (`release_signature`). Ändert er sich zwischen zwei Scans, gilt das als neues Release und der Künstler fällt zurück in die schnellste Stufe.
2. **Release-Jahr aus YT Music** — greift schon beim allerersten Lauf, sodass Karteileichen sofort im langen Intervall landen. YT Music liefert nur das Jahr; gerechnet wird mit dem Jahresende, damit die Freshness eher über- als unterschätzt wird.

Fehlen beide Signale — typisch für den YouTube-Kanal-Fallback, der keine Release-Daten ausliefert — zählt ersatzweise, seit wann ohne Neuigkeit zugeschaut wird. Solche Künstler werden anfangs bei jedem Lauf geprüft und drosseln sich über Wochen selbst ein.

Der Zustand liegt in `channel_state` in der State-DB. Bestehende Datenbanken werden beim ersten Start automatisch migriert; der erste Scan eines Künstlers zählt nie als "neues Release".

Eine Nebenwirkung: löschst du eine lokale Datei eines inaktiven Künstlers, wird sie erst beim nächsten fälligen Scan nachgeladen — oder sofort mit `sync --all` bzw. `sync --artist X`.

### Überblick und Bypass

```bash
music-sync schedule            # Tabelle: letzter Scan, letztes Release, Intervall, nächster Scan
music-sync sync --all          # Zeitplan ignorieren, alle Künstler prüfen
music-sync sync --artist X     # Ein Künstler explizit — umgeht den Zeitplan ebenfalls
music-sync sync --refresh      # API-Cache verwerfen — umgeht den Zeitplan ebenfalls
```

Anpassen über `scan_schedule` in der `config.yaml` (siehe `config.example.yaml`), abschalten mit `scan_schedule.enabled: false`. Playlists sind nicht Teil des Zeitplans — sie werden weiterhin bei jedem Lauf abgefragt, da sich ihr Inhalt jederzeit ändern kann.

---

## Konfiguration (`config.yaml`)

Siehe `config.example.yaml` für ein vollständiges Beispiel. Wichtigste Felder:

| Feld                    | Default       | Beschreibung                                |
|-------------------------|---------------|---------------------------------------------|
| `music_dir`             | —             | Pfad zur lokalen Bibliothek                 |
| `download_dir`          | —             | Zielpfad für Downloads                      |
| `cookies_file`          | —             | Optionale YT Music Premium Cookies          |
| `min_free_space_mb`     | 500           | Min. freier Speicher vor Download           |
| `fuzzy_match_threshold` | 85            | 0-100, höher = strenger                     |
| `log_level`             | INFO          | DEBUG / INFO / WARNING / ERROR              |
| `filter_keywords`       | siehe Default | Substrings die Songs überspringen lassen    |
| `scan_schedule`         | aktiv         | Adaptive Rescan-Intervalle (siehe oben)     |
| `artists`               | —             | Liste mit `name` + `ytmusic_id`/`youtube_url` |

---

## Tests

```bash
pip install pytest
pytest
```

---

## Lizenz

Privat — kein offizielles Tool. Verwendung von YouTube/YT-Music-Inhalten unterliegt deren Nutzungsbedingungen.
