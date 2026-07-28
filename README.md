# Spatial Hub: Z-Wave

Zeigt das Z-Wave-Netz auf dem Grundriss: den Controller, jeden Knoten in
seinem Bereich und dazwischen eine Linie, deren Farbe sagt, wie gut die
Verbindung ist.

Diese Integration rendert nichts selbst. Sie meldet ihre Daten bei
[Spatial Hub](https://github.com/Chance-Konstruktion) an — der Hub
entscheidet, wo gezeichnet wird. Ohne installierten Hub tut sie nichts,
kostet aber auch nichts.

## Warum eine eigene Integration

Z-Wave JS ist die einzige Integration, die ihre eigene Topologie schon
kennt: welcher Knoten mit dem Controller spricht, wie stark das Signal
war, wie viele Nachrichten durchkamen. Nichts davon steht in der
Geräte-Registry, der generische Adapter des Hubs kann es also nicht sehen.
Deshalb ein eigenes Paket statt eines Sonderfalls im Hub.

## Installation

1. `custom_components/spatial_zwave` nach `<config>/custom_components/`
   kopieren.
2. Home Assistant neu starten.
3. **Einstellungen → Geräte & Dienste → Integration hinzufügen → „Spatial
   Hub: Z-Wave"**.

Es gibt nichts einzustellen — der Dialog hat genau einen Knopf, und mehr
als eine Instanz wird abgelehnt.

Voraussetzungen: eine laufende Z-Wave-JS-Integration und der Spatial Hub.
Beides ist optional in dem Sinn, dass ohne sie nichts kaputtgeht; sichtbar
wird die Ebene aber erst mit beiden.

## Woher die Daten kommen

Zwei Quellen, in dieser Reihenfolge:

1. **Der laufende Z-Wave-JS-Treiber** (`hass.data["zwave_js"]`) — hier
   liegen Controller, Knoten und Live-Statistiken. Das sind Interna einer
   fremden Integration und kein zugesichertes Interface, deshalb ist jeder
   einzelne Zugriff defensiv.
2. **Die Geräte-Registry** — öffentlich, stabil und immer da. Kein
   Signalpegel, aber `via_device`, also zeichnet der Stern trotzdem.

Passt (1) nicht zu dem, was erwartet wird, fällt die Ebene still auf (2)
zurück und schreibt das in ihre Metadaten (`quelle: driver` bzw.
`registry`), statt zu verschwinden. Ein Grundriss, der nach einem
HA-Update die Z-Wave-Ebene verliert, ist schlimmer als einer, der die
RSSI-Werte verliert.

Aktualisiert wird alle **60 Sekunden**. Z-Wave JS sendet kein Signal, auf
das sich hier lauschen ließe, und die Statistiken bewegen sich langsam —
ein langsamer Takt ist ehrlicher, als so zu tun, als käme es gepusht.

## Was gezeichnet wird

**Knoten**

| Feld | Herkunft |
| --- | --- |
| Bereich | der Bereich, dem das Gerät in HA schon zugeordnet ist |
| Zustand | `alive`/`awake` → `online`, `asleep` → `asleep`, `dead` → `offline` |
| Metadaten | Hersteller, Modell, Firmware, `rssi`, `gesendet`, `verloren` |

`asleep` bleibt bewusst ein eigener Zustand: Batteriegeräte schlafen
nachts, und sie auf „offline" abzuflachen würde jede Nacht das halbe Haus
rot färben.

**Kanten**

Jeder Knoten bekommt eine gestrichelte Linie zum Controller. Gestrichelt,
weil Z-Wave über Repeater routet — die Linie bedeutet „vom Controller
erreichbar", nicht „direkter Funkweg".

Die Qualität kommt aus dem RSSI in dBm, mit absichtlich breiten Bändern
(der Wert springt zwischen zwei Messungen um mehrere dB, und ein Plan, der
jede Minute die Farbe wechselt, ist Rauschen):

| RSSI | Qualität |
| --- | --- |
| ≥ −70 dBm | `good` |
| −70 … −85 dBm | `fair` |
| < −85 dBm | `poor` |
| nicht lesbar | `unknown` |

## Aufbau

```
custom_components/spatial_zwave/
├── __init__.py               Setup und Unload des Config-Entries
├── config_flow.py            Ein-Klick-Flow, nur eine Instanz
├── const.py                  DOMAIN
├── spatial.py                die eigentliche Arbeit: Knoten und Kanten
├── spatial_hub_provider.py   Kopie des Hub-Shims (nicht bearbeiten)
├── manifest.json
└── strings.json
```

`spatial_hub_provider.py` wird bewusst **kopiert und nicht importiert**:
So hat diese Integration keinerlei Import vom Hub, funktioniert also auch
dann, wenn der Hub fehlt, eine andere Version hat oder im laufenden
Betrieb entfernt wird. Änderungen daran gehören stromaufwärts, nicht
hierher.

## Lizenz

MIT — siehe [LICENSE](LICENSE).
