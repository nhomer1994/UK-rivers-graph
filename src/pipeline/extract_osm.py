import os
import time
from pathlib import Path
import yaml
import requests
import json

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


def load_config():
    """Loads the spatial parameters from the config.yaml file."""
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def build_overpass_query(bbox):
    """
    Constructs an Overpass QL query using a bounding box.
    BBox format in YAML: [MinLat, MinLon, MaxLat, MaxLon]
    Overpass expects: (MinLat, MinLon, MaxLat, MaxLon)
    """
    bbox_str = f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"
    
    # Overpass QL block requesting water works and wastewater systems
    query = f"""
    [out:json][timeout:180];
    (
      node["man_made"="water_works"]({bbox_str});
      way["man_made"="water_works"]({bbox_str});
      node["man_made"="wastewater_plant"]({bbox_str});
      way["man_made"="wastewater_plant"]({bbox_str});
    );
    out center;
    """
    return query

def fetch_osm_data():
    """Executes the query against the live Overpass API and saves the file."""
    print("Loading project configurations...")
    config = load_config()
    bbox = config["spatial_processing"]["uk_bbox"]
    
    print(f"Formulating Overpass query for Bounding Box: {bbox}")
    query = build_overpass_query(bbox)
    
    # prefer the Overpass "interpreter" endpoint; include fallbacks
    endpoints = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.openstreetmap.fr/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    ]

    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "User-Agent": "UK-rivers-graph/1.0 (+https://github.com/nhomer1994)"
    }
    timeout = 180

    print("Contacting OpenStreetMap Overpass API servers (This can take up to 2 minutes)...")
    start_time = time.time()

    response = None
    for url in endpoints:
        print(f"Trying Overpass endpoint: {url}")
        try:
            resp = requests.post(url, data={"data": query}, headers=headers, timeout=timeout)
        except requests.exceptions.RequestException as e:
            print(f"Request to {url} failed: {e}")
            continue

        if resp.status_code == 200:
            response = resp
            break
        elif resp.status_code == 429:
            # rate limited - retry a few times with backoff
            backoff = 5
            max_retries = 3
            retried = 0
            print(f"Endpoint {url} returned 429 (rate limited). Retrying up to {max_retries} times...")
            while retried < max_retries:
                time.sleep(backoff)
                retried += 1
                backoff *= 2
                try:
                    resp = requests.post(url, data={"data": query}, headers=headers, timeout=timeout)
                except requests.exceptions.RequestException as e:
                    print(f"Retry {retried} to {url} failed: {e}")
                    continue
                if resp.status_code == 200:
                    response = resp
                    break
                print(f"Retry {retried} to {url} returned {resp.status_code}")
            if response is not None:
                break
            else:
                print(f"Giving up on {url} after {max_retries} retries.")
        else:
            print(f"Endpoint {url} returned status {resp.status_code}")

    if response is None:
        print("\nAll Overpass endpoints failed. No response obtained.")
        print("Common causes: large bounding box (server rejects oversized queries), rate limiting, or temporary blocks.")
        print("Suggestions:")
        print(" - Reduce the bbox and query area, or split the bbox into tiles and request each separately.")
        print(" - Wait a few minutes and retry (rate limits may expire).")
        print(" - Ensure your User-Agent identifies the application.")
        return
    
    if response.status_code == 200:
        elapsed = time.time() - start_time
        print(f"Data successfully fetched in {elapsed:.2f} seconds!")
        
        # Ensure target data directory exists
        os.makedirs("data/raw", exist_ok=True)
        output_file = "data/raw/osm_water_infrastructure.json"
        
        with open(output_file, "w") as f:
            json.dump(response.json(), f, indent=2)
            
        print(f"Raw data safely written to: {output_file}")
    else:
        print(f"Error: Overpass API returned Status Code {response.status_code}")
        print(response.text)

if __name__ == "__main__":
    fetch_osm_data()
