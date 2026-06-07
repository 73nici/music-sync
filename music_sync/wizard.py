from __future__ import annotations

from pathlib import Path

import click
import yaml

from .config import DEFAULT_FILTER_KEYWORDS


def run_wizard(config_path: Path) -> None:
    """Interactive first-run wizard. Writes config.yaml to the given path."""
    click.echo("=== Music-Sync First-Run Wizard ===\n")

    if config_path.exists():
        if not click.confirm(f"{config_path} existiert bereits. Überschreiben?", default=False):
            click.echo("Abgebrochen.")
            return

    music_dir = click.prompt(
        "Pfad zum lokalen Musik-Ordner",
        type=click.Path(exists=True, file_okay=False, path_type=Path),
    )

    download_dir = click.prompt(
        "Pfad zum Download-Ordner (kann gleich Musik-Ordner sein)",
        type=click.Path(file_okay=False, path_type=Path),
        default=str(music_dir),
    )

    cookies_file: Path | None = None
    if click.confirm("YouTube Music Premium Cookies einrichten?", default=False):
        cookies_file = click.prompt(
            "Pfad zur cookies.txt",
            type=click.Path(dir_okay=False, path_type=Path),
        )

    pot_provider_url: str | None = None
    if click.confirm(
        "bgutil PO-Token-Provider nutzen (authentischere YouTube-Requests)?",
        default=True,
    ):
        pot_provider_url = click.prompt(
            "PoT-Provider URL",
            default="http://127.0.0.1:4416",
        )

    min_free_space_mb = click.prompt(
        "Minimaler freier Speicherplatz vor Download (MB)", type=int, default=500
    )
    fuzzy_threshold = click.prompt(
        "Fuzzy-Match Schwelle (0-100, höher = strenger)", type=int, default=85
    )
    log_level = click.prompt(
        "Log-Level", type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]), default="INFO"
    )

    artists: list[dict] = []
    click.echo("\nNun fügst du Künstler hinzu (Enter bei leerem Namen beendet die Eingabe).")
    while True:
        name = click.prompt("Künstler-Name", default="", show_default=False).strip()
        if not name:
            break
        kind = click.prompt("Quelle", type=click.Choice(["ytmusic", "youtube"]), default="ytmusic")
        if kind == "ytmusic":
            ytmusic_id = click.prompt("YT Music Channel-ID (browseId)").strip()
            artists.append({"name": name, "ytmusic_id": ytmusic_id})
        else:
            url = click.prompt("YouTube Channel-URL").strip()
            artists.append({"name": name, "youtube_url": url})

    if not artists:
        click.echo(
            "Hinweis: keine Künstler eingetragen — du kannst sie später in config.yaml ergänzen."
        )
        artists.append({"name": "Beispiel-Künstler", "ytmusic_id": "REPLACE_ME"})

    data: dict = {
        "music_dir": str(music_dir),
        "download_dir": str(download_dir),
        "min_free_space_mb": min_free_space_mb,
        "fuzzy_match_threshold": fuzzy_threshold,
        "log_level": log_level,
        "filter_keywords": list(DEFAULT_FILTER_KEYWORDS),
        "artists": artists,
    }
    if cookies_file:
        data["cookies_file"] = str(cookies_file)
    if pot_provider_url:
        data["pot_provider_url"] = pot_provider_url

    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True)

    click.echo(f"\nConfig geschrieben: {config_path}")
    click.echo("Bearbeite die Datei bei Bedarf manuell und starte 'music-sync sync'.")
