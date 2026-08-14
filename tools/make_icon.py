#!/usr/bin/env python3
"""Das Provider-Icon aus dem Hub-Icon ableiten.

    python3 tools/make_icon.py

Die sieben Repositories gehoeren zusammen, also sollen sie auch so
aussehen: dasselbe Haus mit seinen Ebenen, und ein Abzeichen unten
rechts, das sagt, welcher Anbieter es ist. Ein voellig eigenes Motiv je
Anbieter wuerde die Verwandtschaft verschweigen -- und sechs Motive zu
pflegen ist sechsmal die Arbeit.

Die Grundlage wird nicht kopiert, sondern beim Bauen aus dem Hub geholt.
Eine Kopie in jedem Anbieter waere die siebte Datei, die auseinanderlaeuft
-- genau der Fehler, den der SDK-Abgleich in tests/ schon einmal gefunden
hat. Das GitLab ist ohne Anmeldung lesbar, also geht das direkt.

Erzeugt werden die vier Brand-Dateien nach Home-Assistant-Konvention und
ein Avatar fuer GitLab, der unter der 200-KiB-Grenze der Instanz bleibt.
"""

from __future__ import annotations

import argparse
import io
import math
import sys
import urllib.error
import urllib.request
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFilter
except ImportError:  # pragma: no cover - Hinweis statt Absturz
    sys.exit("Pillow fehlt:  pip install pillow")

WURZEL = Path(__file__).resolve().parents[1]
BRAND = WURZEL / "custom_components" / "spatial_zwave" / "brand"

BASIS_URL = (
    "https://gitlab.schanz.ipv64.net/chance-konstruktion/ha-spatial-hub"
    "/-/raw/main/custom_components/spatial_hub/brand/icon%402x.png"
)

# Z-Wave sendet auf 868 MHz -- lange Wellen, die durch Waende gehen. Das
# Abzeichen zeigt deshalb Wellen, und zwar breitere als das WLAN-Zeichen,
# das im Grundbild schon vorkommt: Zwei Funk-Symbole nebeneinander muessen
# sich auf den ersten Blick unterscheiden.
ZWAVE_BLAU = (26, 86, 168, 255)
ZWAVE_HELL = (94, 174, 255, 255)

# Die 200-KiB-Grenze der GitLab-Instanz. 384 px lagen beim Hub-Icon mit
# 237 KiB darueber, deshalb wird die Kantenlaenge hier gesucht statt geraten.
AVATAR_GRENZE = 200 * 1024
AVATAR_KANTEN = (384, 352, 320, 288, 256)


def basis_holen(pfad: Path | None) -> Image.Image:
    """Das Hub-Icon: aus einer Datei, sonst aus dem GitLab."""
    if pfad:
        return Image.open(pfad).convert("RGBA")
    try:
        with urllib.request.urlopen(BASIS_URL, timeout=20) as antwort:
            return Image.open(io.BytesIO(antwort.read())).convert("RGBA")
    except (urllib.error.URLError, TimeoutError, OSError) as fehler:
        sys.exit(
            f"Grundbild nicht erreichbar ({fehler}).\n"
            f"  {BASIS_URL}\n"
            "Alternativ die Datei lokal angeben:\n"
            "  python3 tools/make_icon.py --basis ../ha-spatial-hub/"
            "custom_components/spatial_hub/brand/icon@2x.png"
        )


def wellen(groesse: int) -> Image.Image:
    """Das Abzeichen: drei Bogen, die nach aussen schwaecher werden."""
    # Vierfach gezeichnet und dann verkleinert -- Bogen, die direkt in der
    # Zielgroesse gezogen werden, haben harte Treppen an den Flanken.
    s = groesse * 4
    bild = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    stift = ImageDraw.Draw(bild)

    rand = s * 0.04
    stift.ellipse([rand, rand, s - rand, s - rand], fill=ZWAVE_BLAU)
    stift.ellipse(
        [rand, rand, s - rand, s - rand],
        outline=(255, 255, 255, 235), width=int(s * 0.035),
    )

    # Ursprung der Wellen: unten links im Abzeichen, wie bei einer Antenne.
    mx, my = s * 0.30, s * 0.72
    for i, (radius, staerke, deckung) in enumerate(
        ((0.17, 0.052, 255), (0.30, 0.048, 215), (0.43, 0.044, 165))
    ):
        r = s * radius
        stift.arc(
            [mx - r, my - r, mx + r, my + r],
            start=268, end=362,
            fill=ZWAVE_HELL[:3] + (deckung,),
            width=max(1, int(s * staerke)),
        )
    # Der Punkt, aus dem sie kommen.
    p = s * 0.045
    stift.ellipse([mx - p, my - p, mx + p, my + p], fill=(255, 255, 255, 255))

    return bild.resize((groesse, groesse), Image.LANCZOS)


def _ueberstand(bild: Image.Image, x: int, y: int, gross: int) -> float:
    """Anteil des Abzeichens, der neben dem Motiv liegt (0 = sitzt ganz drauf).

    An einer gerundeten Ecke ist das nicht selbstverstaendlich, und ein halb
    ueberstehendes Abzeichen faellt auf hellem Hintergrund sofort auf. Statt
    das per Augenmass zu beurteilen, wird der Alphakanal darunter gelesen.
    """
    grund = bild.getchannel("A").crop((x, y, x + gross, y + gross))
    rund = Image.new("L", (gross, gross), 0)
    ImageDraw.Draw(rund).ellipse([0, 0, gross - 1, gross - 1], fill=255)
    # Schwelle 200, nicht 250: Das Grundbild ist nirgends voll deckend -- im
    # Inneren liegt der Alphakanal bei 250 bis 253. Mit 250 haette dieser Test
    # immer angeschlagen, auch mitten im Haus, und waere damit kein Test
    # gewesen, sondern eine Sperre.
    draussen = sum(
        1 for a, m in zip(grund.getdata(), rund.getdata()) if m > 128 and a < 200
    )
    return draussen / (math.pi * (gross / 2) ** 2)


def zusammensetzen(basis: Image.Image, kante: int) -> Image.Image:
    """Grundbild in Zielgroesse, Abzeichen unten rechts daraufgesetzt."""
    bild = basis.resize((kante, kante), Image.LANCZOS)

    # 0.26 statt 0.40: Beim ersten Versuch verdeckte das Abzeichen ein Viertel
    # des Hauses und ragte ueber die gerundete Ecke hinaus -- es sah aufgeklebt
    # aus statt zugehoerig. Ein Abzeichen soll kennzeichnen, nicht uebernehmen.
    gross = int(kante * 0.26)
    abzeichen = wellen(gross)

    # Der Abstand zur Kante wird gesucht, nicht gesetzt: Wie weit die Rundung
    # des Grundbildes hereinreicht, haengt am Motiv -- und ein fester Wert waere
    # beim naechsten Bild wieder falsch. Der kleinste Abstand gewinnt, bei dem
    # nichts mehr uebersteht; so bleibt das Abzeichen so weit aussen wie moeglich.
    # Die Rundung des Grundbildes reicht weit herein: Auf der Diagonalen ist
    # schon bei 90 % der Kante nichts mehr. Der Suchbereich geht deshalb bis
    # 20 % -- gemessen, nicht angenommen.
    for anteil in (0.055, 0.07, 0.085, 0.10, 0.115, 0.13, 0.15, 0.17, 0.20):
        x = y = kante - gross - int(kante * anteil)
        if _ueberstand(bild, x, y, gross) == 0:
            break
    else:
        raise SystemExit(
            f"Bei {kante} px sitzt das Abzeichen selbst mit 20 % Abstand nicht "
            "vollstaendig auf dem Motiv -- Groesse verringern."
        )

    # Schatten darunter, sonst klebt das Abzeichen flach auf dem Motiv.
    schatten = Image.new("RGBA", bild.size, (0, 0, 0, 0))
    rund = Image.new("RGBA", (gross, gross), (0, 0, 0, 0))
    ImageDraw.Draw(rund).ellipse([0, 0, gross - 1, gross - 1], fill=(0, 0, 0, 150))
    schatten.paste(rund, (x, y + max(1, int(kante * 0.012))), rund)
    schatten = schatten.filter(ImageFilter.GaussianBlur(max(1, kante * 0.012)))

    bild = Image.alpha_composite(bild, schatten)
    bild.paste(abzeichen, (x, y), abzeichen)
    return bild


def avatar_schreiben(basis: Image.Image, ziel: Path) -> None:
    """Groesste Kantenlaenge, die unter der Instanz-Grenze bleibt."""
    for kante in AVATAR_KANTEN:
        zusammensetzen(basis, kante).save(
            ziel, "PNG", optimize=True, compress_level=9
        )
        groesse = ziel.stat().st_size
        if groesse < AVATAR_GRENZE:
            luft = (AVATAR_GRENZE - groesse) / 1024
            print(
                f"  {ziel.name:24} {kante}x{kante}  "
                f"{groesse / 1024:6.1f} KiB  ({luft:.0f} KiB Luft)"
            )
            return
    sys.exit(
        f"Selbst {AVATAR_KANTEN[-1]} px bleiben nicht unter "
        f"{AVATAR_GRENZE // 1024} KiB -- das Grundbild ist zu detailreich."
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--basis", type=Path, help="Hub-Icon lokal statt aus dem GitLab")
    args = p.parse_args()

    basis = basis_holen(args.basis)
    if basis.size[0] != basis.size[1]:
        sys.exit(f"Grundbild ist nicht quadratisch: {basis.size}")

    BRAND.mkdir(parents=True, exist_ok=True)
    for name, kante in (("icon.png", 256), ("icon@2x.png", 512),
                        ("logo.png", 256), ("logo@2x.png", 512)):
        ziel = BRAND / name
        zusammensetzen(basis, kante).save(
            ziel, "PNG", optimize=True, compress_level=9
        )
        print(f"  {name:24} {kante}x{kante}  {ziel.stat().st_size / 1024:6.1f} KiB")

    avatar_schreiben(basis, WURZEL / "avatar.png")
    print("\nAvatar setzen (Token aus der Push-URL):")
    print("  curl -X PUT -H \"PRIVATE-TOKEN: $TOKEN\" -F avatar=@avatar.png \\")
    print("    https://gitlab.schanz.ipv64.net/api/v4/projects/"
          "chance-konstruktion%2Fha-spatial-zwave")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
