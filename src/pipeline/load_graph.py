import os
import pandas as pd
from dotenv import load_dotenv
from neo4j import GraphDatabase

# Load the AuraDB credentials from your Codespace environment secrets
load_dotenv()

URI = os.getenv("NEO4J_URI")
USER = os.getenv("NEO4J_USER")
PASSWORD = os.getenv("NEO4J_PASSWORD")

# Safe batch size to prevent hitting memory limits on the cloud Free Tier
BATCH_SIZE = 5000

def get_driver():
    """Initializes the secure Neo4j Bolt driver connection."""
    if not all([URI, USER, PASSWORD]):
        raise ValueError("Missing database configuration environment variables in .env")
    return GraphDatabase.driver(URI, auth=(USER, PASSWORD))

def load_nodes(session):
    """Loads the HydroNode structures in batches."""
    print("Loading Hydro Nodes into AuraDB...")
    df = pd.read_csv("data/processed/hydro_nodes.csv")
    records = df.to_dict(orient="records")
    
    query = """
    UNWIND $batch AS row
    MERGE (n:HydroNode {id: row.node_id})
    ON CREATE SET n.location = point({latitude: toFloat(row.latitude), longitude: toFloat(row.longitude)})
    """
    
    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i:i+BATCH_SIZE]
        session.run(query, batch=batch)
    print(f"Successfully loaded {len(df)} unique HydroNode records.")

def load_edges(session):
    """Loads the linear river relationships in batches."""
    print("Loading River FLOWS_INTO relationships into AuraDB...")
    df = pd.read_csv("data/processed/hydro_edges.csv")
    records = df.to_dict(orient="records")
    
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
    
    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i:i+BATCH_SIZE]
        session.run(query, batch=batch)
    print(f"Successfully loaded {len(df)} linear flow segments.")

def load_wtws(session):
    """Loads and links the Treatment Assets in batches."""
    print("Loading and linking OpenStreetMap Treatment Plants...")
    df = pd.read_csv("data/processed/snapped_wtws.csv")
    records = df.to_dict(orient="records")
    
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
    
    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i:i+BATCH_SIZE]
        session.run(query, batch=batch)
    print(f"Successfully uploaded and linked {len(df)} infrastructure assets.")

def run_pipeline():
    driver = get_driver()
    with driver.session() as session:
        # Step-by-step ingestion cascade
        load_nodes(session)
        load_edges(session)
        load_wtws(session)
    driver.close()
    print("\n🎉 INGESTION PIPELINE FINISHED! Your UK River Graph is live in the cloud.")

if __name__ == "__main__":
    run_pipeline()
