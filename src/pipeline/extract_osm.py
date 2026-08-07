import os
import time
import yaml
import requests
import json

def load_config():
    """Loads the spatial parameters from the config.yaml file."""
    config_path = "config.yaml"
    with open(config_path, "r") as f:
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
    
    url = "https://overpass-api.de"
    
    print("Contacting OpenStreetMap Overpass API servers (This can take up to 2 minutes)...")
    start_time = time.time()
    
    response = requests.post(url, data={"data": query})
    
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
