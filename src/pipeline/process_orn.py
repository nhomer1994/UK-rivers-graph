import os
import yaml
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, LineString, GeometryCollection

def load_config():
    """Loads the spatial parameters from the config.yaml file."""
    with open("config.yaml", "r") as f:
        return yaml.safe_load(f)

def process_hydro_network():
    config = load_config()
    bbox = config["spatial_processing"]["uk_bbox"]
    max_dist = config["spatial_processing"]["max_snap_distance_degrees"]

    # Locate the extracted GeoPackage file
    raw_dir = "data/raw"
    processed_dir = "data/processed"
    os.makedirs(processed_dir, exist_ok=True)
    gpkg_files = [f for f in os.listdir(raw_dir) if f.endswith(".gpkg")]
    if not gpkg_files:
        raise FileNotFoundError("No .gpkg file found in data/raw/. Please run download_orn.py first.")
    
    gpkg_path = os.path.join(raw_dir, gpkg_files[0])
    print(f"Reading latest GeoPackage layer: {gpkg_path}...")
    
    # Read the linear river features layer into a GeoDataFrame
    # Passing layer=0 automatically grabs the primary vector layer.
    gdf = gpd.read_file(gpkg_path, layer=0)
    print(f"Successfully loaded {len(gdf)} raw river links.")

    # Generate the edges
    print("Extracting topological edges and attributes...")
    edges = []
    nodes_accumulator = []

    for idx, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
            
        # Get exact start (upstream) and end (downstream) points of the LineString
        # Handle multipart geometries (MultiLineString, GeometryCollection) by
        # selecting the longest LineString sub-geometry as a representative.
        linestring = None
        if isinstance(geom, LineString):
            linestring = geom
        else:
            # Try to find the longest LineString component
            try:
                components = [g for g in geom.geoms if isinstance(g, LineString)]
            except Exception:
                components = []

            if components:
                linestring = max(components, key=lambda g: g.length)
            else:
                # No LineString parts found; skip this geometry
                continue

        coords = list(linestring.coords)
        start_pt = coords[0]
        end_pt = coords[-1]
        
        # Form clean string keys for node mapping based on precise coordinates
        start_id = f"NODE_{start_pt[0]:.6f}_{start_pt[1]:.6f}"
        end_id = f"NODE_{end_pt[0]:.6f}_{end_pt[1]:.6f}"
        
        # Calculate length dynamically in kilometers if geometries are lat/lon (WGS84 approx length)
        # OpenRivers defaults to British National Grid (OSGB36).
        # We store coordinates as WGS84 for Neo4j Spatial compatibility.
        
        # Fallback to default fields if specific v2.0 geomorphology tags vary slightly
        river_name = row.get("name", row.get("river_name", "Unnamed Watercourse"))
        stream_order = int(row.get("streamOrder", row.get("stream_order", 1)))
        caba_id = row.get("cabaId", row.get("caba_id", "Unknown"))
        length_m = row.get("length", geom.length) # OSGB36 utilizes meters natively
        
        # Append edge record matching Neo4j LOAD CSV structure
        edges.append({
            "from_node_id": start_id,
            "to_node_id": end_id,
            "river_name": river_name,
            "stream_order": stream_order,
            "caba_id": caba_id,
            "length_km": round(length_m / 1000.0, 3)
        })
        
        # Collect nodes data for the next phase
        nodes_accumulator.append({"id": start_id, "lon": start_pt[0], "lat": start_pt[1]})
        nodes_accumulator.append({"id": end_id, "lon": end_pt[0], "lat": end_pt[1]})

    # Generate the nodes
    print("Consolidating unique coordinate points into graph nodes...")
    df_nodes_raw = pd.DataFrame(nodes_accumulator)
    # Deduplicate nodes hitting the exact same physical coordinates
    df_nodes_unique = df_nodes_raw.drop_duplicates(subset=["id"])

    # Convert paths back to GeoPandas temporarily to re-project coordinates into classic WGS84 Lat/Lon
    # This ensures it maps natively into Neo4j's `point({latitude: x, longitude: y})` function
    geometry = [Point(xy) for xy in zip(df_nodes_unique["lon"], df_nodes_unique["lat"])]
    geo_nodes = gpd.GeoDataFrame(df_nodes_unique, crs=gdf.crs, geometry=geometry)
    
    # Transform coordinates to standard global EPSG:4326 (WGS84 latitude/longitude)
    geo_nodes_wgs84 = geo_nodes.to_crs(epsg=4326)
    
    # Build final node export DataFrame
    final_nodes = pd.DataFrame({
        "node_id": geo_nodes_wgs84["id"],
        "longitude": geo_nodes_wgs84.geometry.x,
        "latitude": geo_nodes_wgs84.geometry.y
    })

    # Convert edge tracking into a standard DataFrame
    final_edges = pd.DataFrame(edges)

    # Export
    nodes_csv = os.path.join(processed_dir, "hydro_nodes.csv")
    edges_csv = os.path.join(processed_dir, "hydro_edges.csv")
    
    final_nodes.to_csv(nodes_csv, index=False)
    final_edges.to_csv(edges_csv, index=False)
    
    print(f"Data pipeline processing complete!")
    print(f"Successfully generated: {len(final_nodes)} unique nodes -> {nodes_csv}")
    print(f"Successfully generated: {len(final_edges)} network edges -> {edges_csv}")

if __name__ == "__main__":
    process_hydro_network()
