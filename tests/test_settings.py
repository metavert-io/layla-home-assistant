"""Reading the options and endpoints from a config entry: defaults, and values out of range or unknown."""

from custom_components.layla.const import DEFAULT_CLIENT_ID, DEFAULT_ONLINE_MINUTES, DEFAULT_UPDATE_MINUTES
from custom_components.layla.model import ALARMS, CORE_ALARMS, READINGS
from custom_components.layla.settings import Endpoints, Options


def test_defaults_are_the_original_behaviour() -> None:
    o = Options.from_options({})
    assert o.update_minutes == DEFAULT_UPDATE_MINUTES == 2
    assert o.online_minutes == DEFAULT_ONLINE_MINUTES == 60
    assert o.properties == frozenset()
    assert o.wants_property("anything")
    assert not o.property_in_name
    assert o.readings == tuple(READINGS)
    assert o.alarms == CORE_ALARMS
    assert o.device_alarms


def test_out_of_range_and_unknown_values() -> None:
    o = Options.from_options(
        {
            "update_minutes": 0,
            "online_minutes": "lots",
            "properties": ["p1", 2],
            "readings": ["noise", "nonsense"],
            "alarms": "smoke_alarm",  # not a list
            "device_alarms": False,
        }
    )
    assert o.update_minutes == 1
    assert o.online_minutes == DEFAULT_ONLINE_MINUTES
    assert o.properties == {"p1", "2"}
    assert o.wants_property("p1") and not o.wants_property("p3")
    assert o.readings == ("noise",)
    assert o.alarms == CORE_ALARMS
    assert not o.device_alarms
    assert Options.from_options({"update_minutes": 500}).update_minutes == 60
    assert Options.from_options({"readings": [], "alarms": []}).readings == ()
    assert Options.from_options({"alarms": list(ALARMS)}).alarms == tuple(ALARMS)


def test_endpoints() -> None:
    assert Endpoints.from_data({}) == Endpoints()
    assert Endpoints().changed() == {}
    custom = Endpoints.from_data({"client_id": "mine", "api_url": "https://layla.example.com/api/"})
    assert custom.api_url == "https://layla.example.com/api"
    assert custom.changed() == {"client_id": "mine", "api_url": "https://layla.example.com/api"}
    assert Endpoints.from_data({"client_id": ""}).client_id == DEFAULT_CLIENT_ID
