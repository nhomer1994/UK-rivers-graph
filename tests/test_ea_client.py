import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.api.ea_client import EnvironmentAgencyClient


class DummyResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_get_station_measurements_filters_user_date_range(monkeypatch):
    payload = {
        "member": [
            {
                "id": "obs-1",
                "phenomenonTime": "2024-12-31T12:00:00Z",
                "observedProperty": {"prefLabel": "Nitrate"},
                "hasResult": {"prefLabel": "5"},
                "hasUnit": "mg/l"
            },
            {
                "id": "obs-2",
                "phenomenonTime": "2025-01-15T08:00:00Z",
                "observedProperty": {"prefLabel": "Nitrate"},
                "hasResult": {"prefLabel": "7"},
                "hasUnit": "mg/l"
            },
            {
                "id": "obs-3",
                "phenomenonTime": "2025-02-01T09:00:00",
                "observedProperty": {"prefLabel": "Phosphate"},
                "hasResult": {"prefLabel": "0.4"},
                "hasUnit": "mg/l"
            },
            {
                "id": "obs-4",
                "phenomenonTime": "2026-01-10T10:00:00Z",
                "observedProperty": {"prefLabel": "Phosphate"},
                "hasResult": {"prefLabel": "0.6"},
                "hasUnit": "mg/l"
            }
        ]
    }

    def fake_get(url, params=None, headers=None, timeout=None):
        return DummyResponse(payload)

    monkeypatch.setattr("requests.get", fake_get)

    client = EnvironmentAgencyClient()
    measurements = client.get_station_measurements("TEST-001", limit=10, start_date="2025-01-01", end_date="2025-12-31")

    assert [m["sample_id"] for m in measurements] == ["obs-2", "obs-3"]
    assert measurements[0]["sample_time"] == "2025-01-15T08:00:00Z"

    range_with_2026 = client.get_station_measurements("TEST-001", limit=10, start_date="2025-01-01", end_date="2026-01-31")
    assert [m["sample_id"] for m in range_with_2026] == ["obs-2", "obs-3", "obs-4"]


def test_find_nearby_stations_keeps_only_target_river_types(monkeypatch):
    payload = {
        "member": [
            {
                "notation": "ST-100",
                "prefLabel": "River Station A",
                "samplingPointType": {"prefLabel": "FRESHWATER - RIVERS"},
                "geometry": {"coordinates": [-2.0, 51.0]},
                "area": {"prefLabel": "River Exe"}
            },
            {
                "notation": "ST-200",
                "prefLabel": "Groundwater Borehole",
                "samplingPointType": {"prefLabel": "GROUNDWATER - BOREHOLE"},
                "geometry": {"coordinates": [-2.1, 51.1]},
                "area": {"prefLabel": "Unknown"}
            },
            {
                "notation": "ST-300",
                "prefLabel": "River Station B",
                "samplingPointType": {"prefLabel": "FRESHWATER - UNSPECIFIED"},
                "geometry": {"coordinates": [-2.2, 51.2]},
                "area": {"prefLabel": "River Severn"}
            }
        ]
    }

    def fake_get(url, params=None, headers=None, timeout=None):
        return DummyResponse(payload)

    monkeypatch.setattr("requests.get", fake_get)

    stations = EnvironmentAgencyClient().find_nearby_stations(51.0, -2.0, distance_km=10)

    assert [station["station_id"] for station in stations] == ["ST-100", "ST-300"]
    assert {station["station_id"] for station in stations} == {"ST-100", "ST-300"}


def test_find_nearby_stations_handles_no_matches_gracefully(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        return DummyResponse({"member": []})

    monkeypatch.setattr("requests.get", fake_get)

    stations = EnvironmentAgencyClient().find_nearby_stations(51.0, -2.0, distance_km=0.5)
    assert stations == []


def test_get_station_measurements_handles_missing_result_fields(monkeypatch):
    payload = {
        "member": [
            {
                "id": "obs-1",
                "phenomenonTime": "2025-01-07T00:00:00+00:00",
                "observedProperty": {"prefLabel": "Temperature"},
                "hasResult": None,
                "hasUnit": "CEL"
            },
            {
                "id": "obs-2",
                "phenomenonTime": "2025-01-07T01:00:00Z",
                "observedProperty": {"altLabel": "Ammonia"},
                "hasResult": {"prefLabel": "0.02"},
                "hasUnit": "mg/l"
            }
        ]
    }

    def fake_get(url, params=None, headers=None, timeout=None):
        return DummyResponse(payload)

    monkeypatch.setattr("requests.get", fake_get)

    client = EnvironmentAgencyClient()
    measurements = client.get_station_measurements("TEST-001", limit=10, start_date="2025-01-01", end_date="2025-12-31")

    assert [m["sample_id"] for m in measurements] == ["obs-1", "obs-2"]
    assert measurements[0]["value"] is None
    assert measurements[1]["value"] == "0.02"
