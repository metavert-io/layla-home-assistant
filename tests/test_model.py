"""Tests for model.py, parsing Layla's answers. They need no Home Assistant: python3 -m unittest tests.test_model"""

import base64
import importlib.util
import json
import pathlib
import sys
import unittest

# model.py on its own, without importing the integration (and so Home Assistant)
_spec = importlib.util.spec_from_file_location("layla_model", pathlib.Path(__file__).parents[1] / "custom_components/layla/model.py")
model = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = model  # dataclasses look the module up
_spec.loader.exec_module(model)

# An invented answer from GET /v1/devices?property_id=…, in the shape Layla's API documents.
DEVICES = [
    {
        "id": "dev-1",
        "property_id": "prop-1",
        "name": "Living room ",
        "device_mac": "AA:BB:CC:00:11:22",
        "serial_number": "SN-TEST",
        "category": "v3.0",
        "device_pillar": "noise",
        "connection_status": "online",
        "last_updated_at": "2026-01-02T03:04:05Z",
        "latest_values": [
            {"name": "noise", "value": 41.5, "min_value": 30, "max_value": 62, "timestamp": "2026-01-02T03:04:00Z"},
            {"name": "occupancy_max", "value": 3, "timestamp": "2026-01-02T03:04:00Z"},
            {"name": "temperature", "value": "70.2"},
            {"name": "outdoor_temperature", "value": 40},
            {"name": "humidity", "value": None},
        ],
        "active_alarms": [
            {"name": "noise_alarm_start", "state": "in_alarm", "first_datapoint_timestamp": "2026-01-02T02:50:00Z"},
            {"name": "mold_alarm", "state": "snoozed"},
        ],
        "alarms": [
            {"name": "co2_alarm", "enabled": True},
            {"name": "tvoc_alarm", "enabled": False},
            {"name": "alarm_schedule"},
        ],
    },
    {"id": "dev-2", "connection_status": "offline", "in_alarm": ["smoke_alarm"], "snoozed": ["noise_alarm_quiet_hours"]},
    {"name": "no id: skipped"},
    "not an object",
]


class ParseDevices(unittest.TestCase):
    def setUp(self):
        self.devs = model.parse_devices(DEVICES)

    def test_devices(self):
        self.assertEqual(sorted(self.devs), ["dev-1", "dev-2"])
        d = self.devs["dev-1"]
        self.assertEqual((d.name, d.model, d.mac, d.online, d.pillar), ("Living room", "Layla 3.0", "AA:BB:CC:00:11:22", True, "noise"))
        self.assertEqual(self.devs["dev-2"].name, "Layla")
        self.assertFalse(self.devs["dev-2"].online)

    def test_readings(self):
        d = self.devs["dev-1"]
        # known readings with a number only: outdoor weather and missing values are left out
        self.assertEqual(d.readings, {"noise": 41.5, "occupancy_max": 3.0, "temperature": 70.2})
        self.assertEqual(d.reading_range["noise"], (30.0, 62.0))
        self.assertNotIn("occupancy_max", d.reading_range)  # no range sent
        self.assertEqual(d.reading_at["noise"], "2026-01-02T03:04:00Z")

    def test_ranges(self):
        def rng(low, high):
            body = [{"id": "a", "latest_values": [{"name": "wifi_rssi", "value": -5, "min_value": low, "max_value": high}]}]
            return model.parse_devices(body)["a"].reading_range.get("wifi_rssi")

        self.assertIsNone(rng(0, 0))  # Layla's "no range"
        self.assertIsNone(rng(None, None))
        self.assertEqual(rng(-6, 0), (-6.0, 0.0))  # a real range that ends at 0
        self.assertEqual(rng(0, 62), (0.0, 62.0))

    def test_alarms(self):
        d = self.devs["dev-1"]
        # a snoozed alarm is still active
        self.assertEqual(d.firing, {"noise_alarm": "2026-01-02T02:50:00Z", "mold_alarm": ""})
        self.assertEqual(d.snoozed, {"mold_alarm"})
        self.assertEqual(d.configured_alarms, {"co2_alarm", "alarm_schedule"})
        offered = d.alarms_offered()
        for a in model.CORE_ALARMS + ("co2_alarm",):
            self.assertIn(a, offered)
        self.assertNotIn("tvoc_alarm", offered)  # turned off in its settings
        self.assertNotIn("alarm_schedule", offered)  # not an alarm
        # the older names-only answer
        self.assertEqual(self.devs["dev-2"].firing, {"smoke_alarm": "", "noise_alarm_quiet_hours": ""})
        self.assertEqual(self.devs["dev-2"].snoozed, {"noise_alarm_quiet_hours"})

    def test_not_a_list(self):
        self.assertEqual(model.parse_devices({"message": "no"}), {})


class Online(unittest.TestCase):
    NOW = model.datetime(2026, 1, 2, 3, 10, tzinfo=model.UTC)

    def test_status_wins(self):
        d = model.parse_devices([{"id": "a", "connection_status": "offline", "last_updated_at": "2026-01-02T03:09:00Z"}], self.NOW)["a"]
        self.assertFalse(d.online)

    def test_recent_report_without_status(self):
        recent = [{"id": "a", "mode": "noise", "latest_values": [{"name": "noise", "value": 40, "timestamp": "2026-01-02T03:05:00"}]}]
        d = model.parse_devices(recent, self.NOW)["a"]
        self.assertTrue(d.online)
        self.assertEqual(d.pillar, "noise")
        self.assertTrue(d.updated_at.startswith("2026-01-02T03:05"))
        # a zoneless time is the property's wall clock: 12:05 in Tokyo is 03:05 UTC
        local = [{"id": "a", "_timezone": "Asia/Tokyo", "latest_values": [{"name": "noise", "value": 40, "timestamp": "2026-01-02T12:05:00"}]}]
        self.assertTrue(model.parse_devices(local, self.NOW)["a"].online)
        stale = [{"id": "a", "last_updated_at": "2026-01-02T02:00:00+00:00"}]
        self.assertFalse(model.parse_devices(stale, self.NOW)["a"].online)
        self.assertFalse(model.parse_devices([{"id": "a"}], self.NOW)["a"].online)

    def test_recent_is_an_option(self):
        stale = [{"id": "a", "last_updated_at": "2026-01-02T02:00:00+00:00"}]
        self.assertTrue(model.parse_devices(stale, self.NOW, recent=model.timedelta(hours=2))["a"].online)
        self.assertFalse(model.parse_devices(stale, self.NOW, recent=model.timedelta(minutes=30))["a"].online)

    def test_clocks_going_back(self):
        # Lisbon, 25 Oct 2026: 01:00-02:00 happens twice (first at UTC+1, then at UTC+0)
        def online(report, now, minutes=10):
            body = [{"id": "a", "_timezone": "Europe/Lisbon", "latest_values": [{"name": "noise", "value": 40, "timestamp": report}]}]
            return model.parse_devices(body, now, recent=model.timedelta(minutes=minutes))["a"].online

        second = model.datetime(2026, 10, 25, 1, 35, tzinfo=model.UTC)  # 01:35 the second time
        self.assertTrue(online("2026-10-25T01:32:00", second))  # three minutes ago, not 63
        first = model.datetime(2026, 10, 25, 0, 40, tzinfo=model.UTC)  # 01:40 the first time
        self.assertTrue(online("2026-10-25T01:38:00", first))  # the second 01:38 hasn't happened yet
        self.assertFalse(online("2026-10-25T00:20:00", second))  # outside the repeated hour: as before

    def test_unknown_zone_is_utc(self):
        body = [{"id": "a", "_timezone": "Not/AZone", "latest_values": [{"name": "noise", "value": 40, "timestamp": "2026-01-02T03:05:00"}]}]
        self.assertTrue(model.parse_devices(body, self.NOW)["a"].online)


class Choices(unittest.TestCase):
    def setUp(self):
        self.dev = model.parse_devices(DEVICES)["dev-1"]

    def test_alarms_chosen(self):
        self.assertEqual(self.dev.alarms_offered(["smoke_alarm"], from_device=False), ["smoke_alarm"])
        # from the device: the ones turned on for it (co2_alarm) and the active ones (noise_alarm, mold_alarm snoozed)
        self.assertEqual(self.dev.alarms_offered([], from_device=True), ["noise_alarm", "co2_alarm", "mold_alarm"])
        self.assertEqual(self.dev.alarms_offered(["not_an_alarm"], from_device=False), [])

    def test_title(self):
        self.assertEqual(self.dev.title(), "Living room")
        self.dev.property_name = "Lakeside"
        self.assertEqual(self.dev.title(with_property=True), "Lakeside Living room")
        self.assertEqual(self.dev.title(with_property=False), "Living room")
        self.dev.name = "Lakeside hall"  # already starts with it
        self.assertEqual(self.dev.title(with_property=True), "Lakeside hall")


class Other(unittest.TestCase):
    def test_alarm_name(self):
        self.assertEqual(model.alarm_name("smoke_alarm_start"), "smoke_alarm")
        self.assertEqual(model.alarm_name("co_alarm_end"), "co_alarm")
        self.assertEqual(model.alarm_name("eco_mode_enabled"), "eco_mode_enabled")

    def test_temperature_unit(self):
        self.assertEqual(model.temperature_unit({"preferences": {"temperature_unit": "c"}}), "C")
        self.assertEqual(model.temperature_unit({"preferences": {}}), "F")
        self.assertEqual(model.temperature_unit(None), "F")

    def test_token_claims(self):
        payload = base64.urlsafe_b64encode(json.dumps({"sub": "u-1", "exp": 1700000000}).encode()).rstrip(b"=").decode()
        self.assertEqual(model.token_claims(f"h.{payload}.s"), {"sub": "u-1", "exp": 1700000000})
        self.assertEqual(model.token_claims("garbage"), {})
        self.assertEqual(model.token_claims("a.!!!.c"), {})


if __name__ == "__main__":
    unittest.main()
