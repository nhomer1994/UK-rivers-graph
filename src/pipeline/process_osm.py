import os
import json
import yaml
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

def load_config():
    """Loads the spatial parameters from the config.yaml file."""
    with open("config.yaml", "r") as f:
        return yaml.safe_load(f)

def process_and_snap_wtws():
    config = load_config()
    
    # Safe maximum snapping threshold of 500 meters.
    MAX_SNAP_DISTANCE_METERS = 500 
    
    raw_osm_path = "data/raw/osm_water_infrastructure.json"
    processed_nodes_path = "data/processed/hydro_nodes.csv"
    output_csv_path = "data/processed/snapped_wtws.csv"
    
    if not os.path.exists(raw_osm_path):
        raise FileNotFoundError(f"Missing {raw_osm_path}. Please run extract_osm.py first.")
    if not os.path.exists(processed_nodes_path):
        raise FileNotFoundError(f"Missing {processed_nodes_path}. Please run process_orn.py first.")

    # Parse OSM JSON data and extract water infrastructure assets
    print("Parsing raw OSM JSON data...")
    with open(raw_osm_path, "r") as f:
        osm_data = json.load(f)
        
    elements = osm_data.get("elements", [])
    plant_records = []
    
    for el in elements:
        lat = el.get("lat", el.get("center", {}).get("lat"))
        lon = el.get("lon", el.get("center", {}).get("lon"))
        
        if lat is None or lon is None:
            continue
            
        tags = el.get("tags", {})
        plant_id = f"WTW_{el.get('type')}_{el.get('id')}"
        plant_name = tags.get("name", f"Unnamed Facility ({el.get('id')})")
        plant_type = tags.get("man_made", "unknown")
        
        plant_records.append({
            "plant_id": plant_id,
            "name": plant_name,
            "type": plant_type,
            "latitude": lat,
            "longitude": lon
        })
        
    df_plants = pd.DataFrame(plant_records)
    print(f"Extracted {len(df_plants)} water infrastructure assets from OSM.")

    # Convert to GeoDataFrame and ensure WGS84 CRS
    geometry_plants = [Point(xy) for xy in zip(df_plants["longitude"], df_plants["latitude"])]
    gdf_plants = gpd.GeoDataFrame(df_plants, crs="EPSG:4326", geometry=geometry_plants)
    
    # Load previously generated river nodes
    df_nodes = pd.read_csv(processed_nodes_path)
    geometry_nodes = [Point(xy) for xy in zip(df_nodes["longitude"], df_nodes["latitude"])]
    gdf_nodes = gpd.GeoDataFrame(df_nodes, crs="EPSG:4326", geometry=geometry_nodes)

    print("Re-projecting layers to British National Grid (EPSG:27700) for distance precision...")
    gdf_plants_meters = gdf_plants.to_crs(epsg=27700)
    gdf_nodes_meters = gdf_nodes.to_crs(epsg=27700)

    # Nearest neighbor spatial join to snap water infrastructure to closest river nodes
    print("Executing high-speed spatial snap to nearest river nodes...")
    snapped_gdf = gpd.sjoin_nearest(
        gdf_plants_meters, 
        gdf_nodes_meters, 
        max_distance=MAX_SNAP_DISTANCE_METERS, 
        distance_col="snap_distance_meters"
    )
    
    # Clean up output DataFrame to retain only relevant fields for export
    # Because 'latitude' and 'longitude' fields existed on both sides, pandas appended suffixes.
    # Pull '_left' which corresponds directly to the original plant values.
    final_wtws = pd.DataFrame({
        "plant_id": snapped_gdf["plant_id"],
        "name": snapped_gdf["name"],
        "type": snapped_gdf["type"],
        "latitude": snapped_gdf["latitude_left"],
        "longitude": snapped_gdf["longitude_left"],
        "nearest_river_node_id": snapped_gdf["node_id"],
        "snap_distance_m": snapped_gdf["snap_distance_meters"].round(2)
    })

    # Drop facilities that sit completely outside our river model catchment grid
    final_wtws = final_wtws.dropna(subset=["nearest_river_node_id"])
    
    # Save clean dataset
    final_wtws.to_csv(output_csv_path, index=False)
    print(f"Map-matching sequence complete! Saved {len(final_wtws)} snapped assets to {output_csv_path}")

if __name__ == "__main__":
    process_and_snap_wtws()
