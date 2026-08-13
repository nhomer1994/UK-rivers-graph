import re
from datetime import datetime, timezone
from typing import List, Dict, Optional

import requests
from pyproj import Transformer


class EnvironmentAgencyClient:
    BASE_URL = "https://environment.data.gov.uk/water-quality"
    PAGE_SIZE = 250

    TARGET_RIVER_TYPES = {
        "FRESHWATER - RIVER TRANSFER",
        "FRESHWATER - UNSPECIFIED",
        "FRESHWATER - RIVERS",
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers["Accept"] = "application/ld+json"
        self.transformer = Transformer.from_crs(
            "EPSG:27700", "EPSG:4326", always_xy=True
        )

    @staticmethod
    def _label(value):
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return (
                value.get("prefLabel")
                or value.get("label")
                or value.get("altLabel")
            )
        return None

    @staticmethod
    def _datetime(value):
        if not value:
            return None
        if isinstance(value, dict):
            value = value.get("@value") or value.get("value")
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return None

    def find_nearby_stations(
        self, lat: float, lon: float, distance_km: float = 1.0
    ) -> List[Dict]:
        """Find EA sampling points near a WGS84 coordinate."""

        url = f"{self.BASE_URL}/sampling-point"
        params = {
            "skip": 0,
            "limit": self.PAGE_SIZE,
            "latitude": round(float(lat), 5),
            "longitude": round(float(lon), 5),
            "radius": float(distance_km),
        }

        try:
            r = self.session.get(url, params=params, timeout=30)
            r.raise_for_status()

            stations = []

            for item in r.json().get("member", []):
                station_type = self._label(item.get("samplingPointType"))

                if station_type not in self.TARGET_RIVER_TYPES:
                    continue

                wkt = (item.get("geometry") or {}).get("asWKT", "")
                match = re.search(
                    r"POINT\s*\(\s*([\d.]+)\s+([\d.]+)\s*\)", wkt
                )
                if not match:
                    continue

                easting, northing = map(float, match.groups())
                longitude, latitude = self.transformer.transform(
                    easting, northing
                )

                area = item.get("area") or item.get("subArea")

                stations.append({
                    "station_id": item.get("notation") or item.get("id"),
                    "label": item.get("prefLabel") or "Unnamed Sampling Point",
                    "latitude": latitude,
                    "longitude": longitude,
                    "watercourse_name": self._label(area) or "Unknown",
                    "sampling_point_type": station_type,
                })

            return stations

        except requests.RequestException as e:
            print(f"❌ EA API call failed: {e}")
            return []

    def get_station_measurements(
        self,
        station_id: str,
        limit: int = 250,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict]:
        """Fetch observations for a station using server-side date filtering."""

        url = (
            f"{self.BASE_URL}/sampling-point/"
            f"{station_id}/observation"
        )

        measurements = []
        skip = 0

        while len(measurements) < limit:
            params = {
                "skip": skip,
                "limit": min(self.PAGE_SIZE, limit - len(measurements)),
            }

            if start_date:
                params["dateFrom"] = start_date
            if end_date:
                params["dateTo"] = end_date

            try:
                r = self.session.get(
                    url, params=params, timeout=30
                )
                r.raise_for_status()
            except requests.RequestException as e:
                print(f"❌ EA observation API failed: {e}")
                return []

            members = r.json().get("member", [])
            if not members:
                break

            for item in members:
                sample_time = self._datetime(
                    item.get("phenomenonTime")
                )
                if not sample_time:
                    continue

                result = item.get("hasResult") or {}
                value = (
                    result.get("value")
                    or result.get("numericValue")
                    or result.get("prefLabel")
                    or item.get("hasSimpleResult")
                ) if isinstance(result, dict) else item.get("hasSimpleResult")

                measurements.append({
                    "sample_id": item.get("id") or item.get("@id"),
                    "sample_time": item.get("phenomenonTime"),
                    "pollutant": (
                        self._label(item.get("observedProperty"))
                        or "Unknown Parameter"
                    ),
                    "value": value,
                    "unit": (
                        self._label(item.get("hasUnit"))
                        or "Coded Result"
                    ),
                })

                if len(measurements) >= limit:
                    break

            if len(members) < params["limit"]:
                break

            skip += len(members)

        return measurements[:limit]
"""           

if __name__ == "__main__":
    # Test coordinates 1: Oxford river corridor
    print("--- RUNNING TEST 1 (OXFORD CORRIDOR) ---")
    client = EnvironmentAgencyClient()
    oxford_stations = client.find_nearby_stations(51.7520, -1.2577, distance_km=5.0)
    print(f"Processed {len(oxford_stations)} locations.")
    if oxford_stations:
        print(f"First Station: {oxford_stations[0]['label']} ({oxford_stations[0]['station_id']})")
        
    # Test coordinates 2: River Exe corridor (Completely separate region)
    print("\n--- RUNNING TEST 2 (RIVER EXE CORRIDOR) ---")
    exe_stations = client.find_nearby_stations(50.720, -3.530, distance_km=5.0)
    print(f"Processed {len(exe_stations)} locations.")
    if exe_stations:
        print(f"First Station: {exe_stations[0]['label']} ({exe_stations[0]['station_id']})")
"""