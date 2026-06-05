#!/usr/bin/env python3
"""Insert resolved artist entries into config.yaml after the Alice Cooper anchor,
preserving the file's existing comments and structure."""
from __future__ import annotations

from pathlib import Path

CONFIG = Path("/mnt/code/music-sync/config.yaml")
ANCHOR = '    ytmusic_id: "UCSjn-oQV136VoKk7FXxxZ0w"'  # Alice Cooper

# (folder_name, field, value) — field is "ytmusic_id" or "youtube_url".
# Order follows the case-insensitive folder sort. Skipped on purpose:
#   Crash! Boom! Bang!, Dance Passion - The Remix Album,
#   Joyride 30th Anniversary Edition, Pearls Of Passion  (= Roxette albums)
#   Man Without Hats (dup of Men Without Hats), "Metallica\n" (corrupted dup)
ENTRIES: list[tuple[str, str, str]] = [
    ("Alphaville", "ytmusic_id", "UC-GWJZkyivsS-0yMjKMH0AA"),
    ("Baltimore", "ytmusic_id", "UCi1V1RX9njQPI5YRVqBD__Q"),  # tag=Baltimora
    ("Beastie Boys", "ytmusic_id", "UCe6E2f1FNQZ0XuCJ4GlONwQ"),
    ("Bee Gees", "ytmusic_id", "UC4GVf3NpBzQiuNVf5EYsI5A"),
    ("Belinda Carlisle", "ytmusic_id", "UCXPAj48W0yCbTjOquiFNhLQ"),
    ("Billy Idol", "ytmusic_id", "UC_R3nYWHZV0tGgbpuDoI0vA"),
    ("Black Sabbath", "ytmusic_id", "UCLCELUuoHbkUxZ9EMHTYebg"),
    ("Blondie", "ytmusic_id", "UCF6I8FH_f6NBEsngIfkZY6g"),
    ("Bonnie Tyler", "ytmusic_id", "UC0BdKEjWDC0hw4Bex9fTnMA"),
    ("Bronski Beat", "ytmusic_id", "UChd-WHoVlFDJdnZslKjIqwA"),
    ("cedriK", "youtube_url", "https://www.youtube.com/channel/UCAJJ6ePtfODYSEywuVgMnlA"),
    ("Creedence Clearwater Revival", "ytmusic_id", "UCRbMcMQeSFVvsyEuOn7uAKQ"),
    ("Culture Club", "ytmusic_id", "UChva71IdUXvTn8uHGtJkB_w"),
    ("Cutting Crew", "ytmusic_id", "UC7CYIif6lYnbE9ouq9XNFRQ"),
    ("Cydron", "ytmusic_id", "UC_K9lZX_IPjqItySAYZlZYw"),
    ("Cyndi Lauper", "ytmusic_id", "UC9I3hbllzsS4QZqNekPE76g"),
    ("Daryl Hall & John Oates", "ytmusic_id", "UC8zbYR5i0gecEZ3iPgm-i9g"),
    ("Dead or Alive", "ytmusic_id", "UCNSBZ4vYV5go9h-iXcjOEBw"),
    ("Depeche Mode", "ytmusic_id", "UC-CcyIM_seGnGL5-2Fsppow"),
    ("Deutsche Vita", "ytmusic_id", "UCBrS9gsd0gA7ue4PGFInj0g"),
    ("Dexys Midnight Runners", "ytmusic_id", "UCph7j0pts6_eqx46iMCC-yA"),
    ("DJDEN!AL", "ytmusic_id", "UCKOJvlZMrRfenBVz5tPv-oA"),
    ("Don Henley", "ytmusic_id", "UCnPPs9X57Sl4dNCyIgLigzQ"),
    ("Eurythmics", "ytmusic_id", "UCQiH3xAP0i48o74BK6EBkMw"),
    ("Fiction Factory", "ytmusic_id", "UCOxf5o2unxxmha9paExVWWw"),
    ("Fleetwood Mac", "ytmusic_id", "UCCzULu3prrEaPvM2ZtkJlYQ"),
    ("Frankie goes to Hollywood", "ytmusic_id", "UC7X7CKd4-aLnn0yfJw6sRjg"),
    ("Genesis", "ytmusic_id", "UCqlnY5lvEp6F52AZSql04qQ"),
    ("Guns N' Roses", "ytmusic_id", "UCSLbbBoUqpin6BE34whSOvA"),
    ("Haddaway", "ytmusic_id", "UCfS_1LLbHxkCHWVL8u2mXlg"),
    ("hollywood-vampires", "ytmusic_id", "UC2bgpg6WqSaVvGlgZNqpZWg"),
    ("Iggy Pop", "ytmusic_id", "UCN2OwEXNYJFzgHvR7912Btg"),
    ("INXS", "ytmusic_id", "UCVHfuJpwPb1AWBLWOwA0McQ"),
    ("JF Jake", "ytmusic_id", "UCbTG-PZjQ4w4ncjo4rCBbRg"),
    ("Joan Jett & The Blackheads", "ytmusic_id", "UCV2f_8wytj9jP-01V4f83lw"),  # =Blackhearts
    ("Joe Cocker", "ytmusic_id", "UCe6m5Nh7b2Za7ln6BUXP8vw"),
    ("John Parr", "ytmusic_id", "UCIiSRGx501rLBlqj6i-VFmA"),
    ("Kenny Loggins", "ytmusic_id", "UCF-DjS6Y9CKZThQf01SYe7w"),
    ("Kim Carnes", "ytmusic_id", "UCUci9NVUThEaPjwXVdDimAQ"),
    ("Kiss", "ytmusic_id", "UCL0dlEc0rXV1CIawUKeme4g"),
    ("Kopf & Hörer", "ytmusic_id", "UCWB6iaDj6YJrp1IJegIT4cQ"),
    ("Laura Branigan", "ytmusic_id", "UChUr6-Fbc5f5FH9f0YNWLfQ"),
    ("Lipps Inc", "ytmusic_id", "UC02eqrW1fCLDZwOKVOA62vQ"),
    ("Madonna", "ytmusic_id", "UCo4CrqhIV_tSOGdDWfVyCsg"),
    ("Men at Work", "ytmusic_id", "UCX1qTEuhbyV7Ie4T8TZsX_Q"),
    ("Men Without Hats", "ytmusic_id", "UCfiWm7YQpPf-4PnHEUQskqA"),
    ("Metallica", "ytmusic_id", "UCGexNm_Kw4rdQjLxmpb2EKw"),
    ("Michael Jackson", "ytmusic_id", "UCoIOOL7QKuBhQHVKL8y7BEQ"),
    ("Michael Sembello", "ytmusic_id", "UCV39jwnX80uVisU64TwicSg"),
    ("Midnight Oil", "ytmusic_id", "UCmQb_c5tEEOXgKxvS7i3Qzg"),
    ("Mike + The Mechanics", "ytmusic_id", "UCak2_SOTrC61nzqli-cNThw"),
    ("Mike Oldfield", "ytmusic_id", "UC61c-7pYk-_AaViXMpShWOg"),
    ("Modern Talking", "ytmusic_id", "UCoQve3vhvnrr_n8GboFptdQ"),
    ("Moti Special", "ytmusic_id", "UCl3vCtmZK6YkcqLqC3cnmEA"),
    ("New Order", "ytmusic_id", "UCXExK7We8VKsIzFFQYNEgBg"),
    ("Nick Kamen", "ytmusic_id", "UCnfPaK892cF_C066QBkpCLg"),
    ("Niklas Dee", "ytmusic_id", "UCWLgmttwhy-ChrIV-tVnaTg"),
    ("Patrick Hernandez", "ytmusic_id", "UCDHeuc8bNUTmlllmdtqsIBA"),
    ("Paul Young", "ytmusic_id", "UCB3qJDg2Dtzw7_cTGKn8dqw"),
    ("Pet Shop Boys", "ytmusic_id", "UCQR2QtBlTT2GTPWt9NCRyKw"),
    ("Phil Collins", "ytmusic_id", "UCzt9gB3XNQYs_2UHvolUZog"),
    ("Queen", "ytmusic_id", "UCEPMVbUzImPl4p8k4LkGevA"),
    ("Rainbirds", "ytmusic_id", "UCJp1cjeWtOP99A9ahJb2cNw"),
    ("Real Life", "ytmusic_id", "UCEgfV9Dsuuva_E2hF1_XLag"),
    ("Rednex", "ytmusic_id", "UCZEgluoVApt0qzsZelPqxcQ"),
    ("ROLEXZ", "ytmusic_id", "UCXjeVNYsczSAR0FCPglEArw"),
    ("Rolling Stones", "ytmusic_id", "UCNYhhkQqeFLUc-YEDcLpSYQ"),
    ("Roxette", "ytmusic_id", "UCm8Brkkx9u_4J7DALxg0n1w"),
    ("Sabrina", "ytmusic_id", "UCCoSG8TJFTXW0SVUPfTIaxA"),  # tag=Sabrina Salerno
    ("Sandra", "ytmusic_id", "UCCUeTp5Qy9EF6apVk-t9kEA"),
    ("Silent Circle", "ytmusic_id", "UCAMt0fyyJvMqLnIMJ63xE3A"),
    ("Soft Cell", "ytmusic_id", "UCqx2-vXNXURrhxbXD0zSIUw"),
    ("Spliff", "ytmusic_id", "UCSVNwkF2TXOjuP7hZ3N_lyQ"),
    ("Survivor", "ytmusic_id", "UC52srG5obKLJ16vRsTqZyZQ"),
    ("T.Rex", "ytmusic_id", "UCdCcCZVec1txJJFSzfZzSkA"),
    ("Tears For Fears", "ytmusic_id", "UCcozhiTOkGB1HCOgdBlEFPA"),
    ("Technogasm", "youtube_url", "https://www.youtube.com/channel/UCKo7pV29OIMzVOs2LoRkN-g"),
    ("Technotronic", "ytmusic_id", "UCu5D8MIZMOLsEnZgzWi4e-w"),
    ("The Animals", "ytmusic_id", "UCcFlzgDVSL9dMUo66cEyWJQ"),
    ("The Buggles", "ytmusic_id", "UCnIpeWNFivBwKP7ujv_03EQ"),
    ("The Cars", "ytmusic_id", "UCu_gFD6YgmN85WjTSIotYcA"),
    ("The Clash", "ytmusic_id", "UCf-a_3DiA07vhQmoEaczDhw"),
    ("The Connels", "ytmusic_id", "UCIPpiDHTztu9YvU1Zlc7bzQ"),  # =The Connells
    ("The Flirts", "ytmusic_id", "UCf1aAJy-SgfuEZXyRv9PZZg"),
    ("The Hooters", "ytmusic_id", "UCRqVtcShW_Tu_9eG2lNJBKg"),
    ("The Human League", "ytmusic_id", "UCrg2H-AeXXcZg_TZ8QBRTKw"),
    ("The Outfield", "ytmusic_id", "UC5TJtEuZGgv1Ci7cGF8gfCw"),
    ("The Police", "ytmusic_id", "UCbsRGw640UF_F7AIwHW-zmg"),
    ("Tiefundton", "ytmusic_id", "UCkCabOz9tfJ9iljcFjoEpOA"),
    ("Toto", "ytmusic_id", "UCewH1MBbYlEZMWx3ZUNywyg"),
    ("Trans-X", "ytmusic_id", "UCuSmZDNK1izm4fQnh1wzZFw"),
    ("Tritzo Music", "youtube_url", "https://www.youtube.com/channel/UCOsTXQ5uhh-aHs4sepaPGTg"),
    ("U2", "ytmusic_id", "UCqIQRxCUGi7hyJisyzv9zYQ"),
    ("Valexus", "ytmusic_id", "UCZqi9XdlIEKGxCY5kiDmvEA"),
    ("Visage", "ytmusic_id", "UCxzisN94DdD8JZ035s86O1w"),
    ("Weimar", "ytmusic_id", "UCVileYGM7VYxv23jEe6OlNA"),
    ("Word of Mouth", "ytmusic_id", "UCn0nqgHn0JmWRhMmyHM4v6g"),
    ("Yazoo", "ytmusic_id", "UCGzAsl2oMcCZX5Xq_q5dI1w"),
]


def main() -> None:
    lines = CONFIG.read_text(encoding="utf-8").splitlines()
    try:
        idx = lines.index(ANCHOR)
    except ValueError:
        raise SystemExit(f"Anchor not found in {CONFIG}")

    # Guard: do not add a name that is already present in the file.
    existing_names = {
        ln.split('name:', 1)[1].strip().strip('"')
        for ln in lines if ln.lstrip().startswith("- name:")
    }

    block: list[str] = []
    added = 0
    for name, field, value in ENTRIES:
        if name in existing_names:
            continue
        block.append(f'  - name: "{name}"')
        block.append(f'    {field}: "{value}"')
        added += 1

    new_lines = lines[: idx + 1] + block + lines[idx + 1 :]
    CONFIG.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    print(f"Inserted {added} artist entries.")


if __name__ == "__main__":
    main()
