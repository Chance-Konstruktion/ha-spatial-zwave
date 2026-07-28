"""Z-Wave against the Spatial Hub conformance kit.

`tests/spatial_hub_conformance.py` is copied verbatim from the hub's
`sdk/` -- it is the same file every provider author is asked to drop in.
If this file ever fails, our provider drifted from the contract, not the
other way round.

It is run against the *driver* path rather than the empty one, because an
empty payload conforms trivially and would prove nothing.
"""

from __future__ import annotations

from spatial_hub_conformance import SpatialHubConformance

from conftest import FakeEntry, FakeHass
from test_spatial import FakeDriver, install_driver


class TestSpatialHubConformance(SpatialHubConformance):
    """The whole integration of the kit: one class, one method."""

    def build_registration(self):
        from custom_components.spatial_zwave.spatial import async_setup_spatial

        hass = FakeHass()
        install_driver(hass, FakeDriver())
        async_setup_spatial(hass, FakeEntry())
        return hass.registrations["spatial_zwave"]
