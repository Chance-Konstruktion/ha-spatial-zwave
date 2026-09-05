"""Zwei Zugriffe aufs Geraeteregister, die Core abgekuendigt hat.

Auf der Anlage standen beide im Protokoll:

* ``device_registry.devices`` als Abbildung zu lesen -- endet 2027.9.
* ``async_get_device(identifiers=...)`` -- endet 2027.8, weil eine
  Kennung ueber Konfigurationseintraege hinweg nicht mehr eindeutig ist.

Diese Datei haelt beide Ersatzwege fest, und zwar in beiden Welten: mit
einem heutigen Core und mit einem, das die neuen Aufrufe noch nicht hat.
Die Integration nennt 2024.4 als Untergrenze, also ist der Rueckfall
kein Zierrat, sondern der Normalfall auf alten Anlagen.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.spatial_zwave.spatial import (
    ZWAVE_DOMAIN,
    _geraet_zu_kennung,
    _registry_entries,
)

KENNUNG = (ZWAVE_DOMAIN, "4242-7")


class _Registry:
    """Nur die Eigenschaft, die gelesen wird."""

    def __init__(self, devices):
        self.devices = devices


class _NeueSicht:
    """Wie Core seit 2025.9: Iterieren liefert die Eintraege.

    Der Indexzugriff ist verboten -- er ist genau das, was auf einer
    echten Anlage die Warnung schreibt. Kommt er doch, faellt der Test.
    """

    def __init__(self, eintraege):
        self._eintraege = list(eintraege)

    def __iter__(self):
        return iter(self._eintraege)

    def __bool__(self):
        return bool(self._eintraege)

    def __getitem__(self, schluessel):  # pragma: no cover - darf nie laufen
        raise AssertionError(
            "Indexzugriff auf registry.devices -- genau das ist abgekuendigt"
        )


def test_neue_sicht_ohne_abbildungszugriff():
    eins, zwei = object(), object()
    assert _registry_entries(_Registry(_NeueSicht([eins, zwei]))) == [eins, zwei]


def test_alte_sicht_wird_aufgeloest():
    eins, zwei = object(), object()
    assert _registry_entries(_Registry({"a": eins, "b": zwei})) == [eins, zwei]


@pytest.mark.parametrize("devices", [None, {}, _NeueSicht([])])
def test_leeres_register_gibt_leere_liste(devices):
    assert _registry_entries(_Registry(devices)) == []


# ── Die Kennungssuche ─────────────────────────────────────────────────


class _HassMitEintraegen:
    def __init__(self, *entry_ids):
        self.config_entries = SimpleNamespace(
            async_entries=lambda domain: [
                SimpleNamespace(entry_id=kennung) for kennung in entry_ids
            ]
            if domain == ZWAVE_DOMAIN
            else []
        )


class _NeuesRegister:
    """Kann die Suche je Eintrag -- wie Core seit 2025.9."""

    def __init__(self, treffer: dict):
        self._treffer = treffer
        self.gefragt: list[tuple] = []

    def async_get_device_by_identifier(self, kennung, entry_id):
        self.gefragt.append((kennung, entry_id))
        return self._treffer.get(entry_id)

    def async_get_device(self, identifiers=None):  # pragma: no cover
        raise AssertionError("der abgekuendigte Weg darf hier nicht laufen")


class _AltesRegister:
    """Kennt nur den alten Aufruf -- wie Core vor 2025.9."""

    def __init__(self, geraet):
        self._geraet = geraet
        self.gefragt = None

    def async_get_device(self, identifiers=None):
        self.gefragt = identifiers
        return self._geraet


def test_sucht_im_eintrag_von_zwave_js():
    geraet = object()
    register = _NeuesRegister({"zwave-1": geraet})
    gefunden = _geraet_zu_kennung(
        _HassMitEintraegen("zwave-1"), register, KENNUNG
    )
    assert gefunden is geraet
    assert register.gefragt == [(KENNUNG, "zwave-1")]


def test_zweiter_stick_wird_auch_gefragt():
    """Ein Haus mit zwei Sticks hat zwei Eintraege -- beide zaehlen."""
    geraet = object()
    register = _NeuesRegister({"zwave-2": geraet})
    gefunden = _geraet_zu_kennung(
        _HassMitEintraegen("zwave-1", "zwave-2"), register, KENNUNG
    )
    assert gefunden is geraet
    assert register.gefragt == [(KENNUNG, "zwave-1"), (KENNUNG, "zwave-2")]


def test_ohne_treffer_kommt_nichts():
    register = _NeuesRegister({})
    assert _geraet_zu_kennung(_HassMitEintraegen("zwave-1"), register, KENNUNG) is None


def test_rueckfall_auf_alten_core():
    geraet = object()
    register = _AltesRegister(geraet)
    gefunden = _geraet_zu_kennung(_HassMitEintraegen("zwave-1"), register, KENNUNG)
    assert gefunden is geraet
    assert register.gefragt == {KENNUNG}
