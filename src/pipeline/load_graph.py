import os
import pandas as pd
from dotenv import load_dotenv
from neo4j import GraphDatabase

# Force clean reload of active workspace secrets
load_dotenv()

URI = os.getenv("NEO4J_URI")
USER = os.getenv("NEO4J_USER")
PASSWORD = os.getenv("NEO4J_PASSWORD")

# Smaller batch size keeps execution memory light for the Aura Free tier
BATCH_SIZE = 1000

def get_driver():
    """Initializes a thread-safe connection to the Neo4j instance."""
    if not all([URI, USER, PASSWORD]):
        raise ValueError("Missing authentication variables. Please re-run secrets injection.")
    return GraphDatabase.driver(URI, auth=(USER, PASSWORD))

def load_nodes_streaming(session):
    """Streams HydroNode records from disk in lightweight explicit chunks."""
    print("Initiating Stream-Ingestion of Hydro Nodes...")
    
    # Read the CSV as a generator to keep Codespace memory footprint low
    csv_reader = pd.read_csv("data/processed/hydro_nodes.csv", chunksize=BATCH_SIZE)
    
    query = """
    UNWIND $batch AS row
    MERGE (n:HydroNode {id: row.node_id})
    ON CREATE SET n.location = point({latitude: toFloat(row.latitude), longitude: toFloat(row.longitude)})
    """
    
    total_loaded = 0
    for chunk in csv_reader:
        # Convert only the current chunk slice into a list of records
        batch_payload = chunk.to_dict(orient="records")
        
        # Execute explicitly inside a write transaction
        session.run(query, batch=batch_payload)
        
        total_loaded += len(batch_payload)
        print(f"   [PROGRESS] Ingested {total_loaded} unique nodes into the cloud...")

    print(f"Node loading complete! Total nodes: {total_loaded}")

def load_edges_streaming(session):
    """Streams and builds river flow segments in explicit chunks."""
    print("Initiating Stream-Ingestion of River FLOWS_INTO relationships...")
    csv_reader = pd.read_csv("data/processed/hydro_edges.csv", chunksize=BATCH_SIZE)
    
    query = """
    UNWIND $batch AS row
    MATCH (upstream:HydroNode {id: row.from_node_id})
    MATCH (downstream:HydroNode {id: row.to_node_id})
    CREATE (upstream)-[:FLOWS_INTO {
        name: row.river_name,
        streamOrder: toInteger(row.stream_order),
        cabaId: row.caba_id,
        lengthKm: toFloat(row.length_km)
    }]->(downstream)
    """
    
    total_loaded = 0
    for chunk in csv_reader:
        batch_payload = chunk.to_dict(orient="records")
        session.run(query, batch=batch_payload)
        total_loaded += len(batch_payload)
        print(f"   [PROGRESS] Built {total_loaded} river flow links...")

    print(f"Relationship loading complete! Total segments: {total_loaded}")

def load_wtws_streaming(session):
    """Streams and maps the OpenStreetMap treatment assets."""
    print("Connecting OpenStreetMap infrastructure assets...")
    csv_reader = pd.read_csv("data/processed/snapped_wtws.csv", chunksize=BATCH_SIZE)
    
    query = """
    UNWIND $batch AS row
    MERGE (p:TreatmentPlant {id: row.plant_id})
    ON CREATE SET 
        p.name = row.name,
        p.type = row.type,
        p.location = point({latitude: toFloat(row.latitude), longitude: toFloat(row.longitude)}),
        p.status = "Operational"
        
    WITH p, row
    MATCH (n:HydroNode {id: row.nearest_river_node_id})
    CREATE (p)-[:CONNECTED_TO]->(n)
    """
    
    total_loaded = 0
    for chunk in csv_reader:
        batch_payload = chunk.to_dict(orient="records")
        session.run(query, batch=batch_payload)
        total_loaded += len(batch_payload)
        print(f"   [PROGRESS] Mapped {total_loaded} infrastructure facilities...")

    print(f"Asset linking complete!")

def run_pipeline():
    driver = get_driver()
    with driver.session() as session:
        load_nodes_streaming(session)
        load_edges_streaming(session)
        load_wtws_streaming(session)
    driver.close()
    print("\nLIVE GRAPH ARCHITECTURE SYNCHRONISED SUCCESSFULLY!")

if __name__ == "__main__":
    run_pipeline()
