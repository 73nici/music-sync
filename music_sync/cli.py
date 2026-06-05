from __future__ import annotations

from pathlib import Path

import click

from .config import Config, load_config
from .logger import setup_logging

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


def _load(ctx: click.Context) -> Config:
    config_path = ctx.obj["config_path"]
    cfg = load_config(config_path)
    setup_logging(cfg.log_file_path, cfg.log_level, to_stdout=ctx.obj["verbose"])
    return cfg


@click.group()
@click.option(
    "--config",
    "config_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=DEFAULT_CONFIG_PATH,
    envvar="MUSIC_SYNC_CONFIG",
    show_default=True,
    help="Pfad zur config.yaml (auch via MUSIC_SYNC_CONFIG env-var)",
)
@click.option("-v", "--verbose", is_flag=True, help="Logs zusätzlich auf stdout ausgeben")
@click.pass_context
def main(ctx: click.Context, config_path: Path, verbose: bool) -> None:
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path
    ctx.obj["verbose"] = verbose


@main.command()
@click.pass_context
def init(ctx: click.Context) -> None:
    """Interaktiver First-Run Wizard."""
    from .wizard import run_wizard

    config_path = ctx.obj["config_path"]
    run_wizard(config_path)


@main.command()
@click.pass_context
def scan(ctx: click.Context) -> None:
    """Lokale Musikbibliothek analysieren und Übersicht ausgeben."""
    from .commands import cmd_scan

    cmd_scan(_load(ctx))


@main.command()
@click.option("--artist", "artist_name", help="Nur diesen Künstler synchronisieren")
@click.option("--dry-run", is_flag=True, help="Vorschau ohne Download")
@click.option(
    "--refresh",
    is_flag=True,
    help="API-Cache ignorieren und Album-Diskografien neu von YT Music abrufen",
)
@click.pass_context
def sync(
    ctx: click.Context, artist_name: str | None, dry_run: bool, refresh: bool
) -> None:
    """Fehlende Songs der konfigurierten Künstler herunterladen."""
    from .commands import cmd_sync

    cmd_sync(_load(ctx), artist_name=artist_name, dry_run=dry_run, refresh=refresh)


@main.command("list-missing")
@click.option("--artist", "artist_name", help="Nur diesen Künstler anzeigen")
@click.option(
    "--refresh",
    is_flag=True,
    help="API-Cache ignorieren und Album-Diskografien neu von YT Music abrufen",
)
@click.pass_context
def list_missing(ctx: click.Context, artist_name: str | None, refresh: bool) -> None:
    """Auflisten welche Songs heruntergeladen würden."""
    from .commands import cmd_list_missing

    cmd_list_missing(_load(ctx), artist_name=artist_name, refresh=refresh)


@main.command("retry-failed")
@click.pass_context
def retry_failed(ctx: click.Context) -> None:
    """Fehlgeschlagene Downloads erneut versuchen."""
    from .commands import cmd_retry_failed

    cmd_retry_failed(_load(ctx))


if __name__ == "__main__":
    main()
