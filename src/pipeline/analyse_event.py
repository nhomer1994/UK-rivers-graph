import os
import sys
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point
from neo4j import GraphDatabase


# ------------------------------------------------------------------
# Project / imports
# ------------------------------------------------------------------

SRC_ROOT = Path(__file__).resolve().parents[1]

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from api.ea_client import EnvironmentAgencyClient


# ------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------

URI = os.getenv("NEO4J_URI")
USER = os.getenv("NEO4J_USER")
PASSWORD = os.getenv("NEO4J_PASSWORD")

GPKG_PATH = (
    Path(__file__).resolve().parents[2] / "src" / "pipeline" / "data" / "raw" / "ORN_v2.gpkg"
)

WGS84 = 4326
METRIC_CRS = 27700


class DownstreamImpactAnalyser:

    def __init__(self):
        if not all([URI, USER, PASSWORD]):
            raise ValueError(
                "Missing NEO4J_URI, NEO4J_USER or NEO4J_PASSWORD."
            )

        self.driver = GraphDatabase.driver(
            URI,
            auth=(USER, PASSWORD),
        )
        self.ea_client = EnvironmentAgencyClient()

    def close(self):
        self.driver.close()

    @staticmethod
    def _load_river_geometry():
        """Index GPKG river geometries by their Neo4j edge IDs."""

        print("🗺️ Loading river geometry...")

        gdf = gpd.read_file(GPKG_PATH, layer=0)

        if gdf.crs is None:
            raise ValueError("River GeoPackage has no CRS.")

        edges = {}

        for geom in gdf.geometry.dropna():

            if geom.is_empty:
                continue

            if geom.geom_type == "LineString":
                line = geom
            else:
                try:
                    lines = [
                        g for g in geom.geoms
                        if g.geom_type == "LineString"
                    ]
                except Exception:
                    continue

                if not lines:
                    continue

                line = max(lines, key=lambda g: g.length)

            coords = list(line.coords)

            if len(coords) < 2:
                continue

            start, end = coords[0], coords[-1]

            key = (
                f"NODE_{start[0]:.6f}_{start[1]:.6f}",
                f"NODE_{end[0]:.6f}_{end[1]:.6f}",
            )

            edges[key] = line

        print(f"✅ Indexed {len(edges):,} GPKG river segments.")

        return edges, gdf.crs

    @staticmethod
    def _purge_ea_stations(session):
        print("🧹 Removing previous EA monitoring stations...")

        session.run(
            "MATCH (s:MonitoringStation) DETACH DELETE s"
        )

        session.run(
            """
            CREATE CONSTRAINT unique_station IF NOT EXISTS
            FOR (s:MonitoringStation)
            REQUIRE s.id IS UNIQUE
            """
        )

    def run_downstream_analysis(
        self,
        plant_id,
        graph_depth=40,
        radius_km=1.0,
        start_date=None,
        end_date=None,
    ):

        print(f"\n🎯 DOWNSTREAM ANALYSIS: {plant_id}")
        print(f"   Depth: {graph_depth} | Radius: {radius_km} km")
        print(f"   Dates: {start_date} → {end_date}")

        with self.driver.session() as session:

            # 1. Clear temporary stations
            self._purge_ea_stations(session)

            # 2. Validate plant
            plant = session.run(
                """
                MATCH (p:TreatmentPlant {id: $id})
                RETURN p.id AS id,
                       p.location.latitude AS lat,
                       p.location.longitude AS lon
                """,
                id=plant_id,
            ).single()

            if not plant:
                raise ValueError(
                    f"Treatment plant {plant_id!r} not found."
                )

            print(
                f"🏭 Plant: {plant['id']} "
                f"({plant['lat']}, {plant['lon']})"
            )

            # 3. Trace downstream edges
            query = f"""
            MATCH (p:TreatmentPlant {{id: $id}})
                -[:CONNECTED_TO]->
                (start:HydroNode)

            MATCH path =
                (start)-[:FLOWS_INTO*..{int(graph_depth)}]->()

            UNWIND relationships(path) AS r

            RETURN DISTINCT
                startNode(r).id AS from_node,
                endNode(r).id AS to_node
            """

            print(f"🌊 Tracing {graph_depth} downstream links...")

            downstream_edges = [
                r.data()
                for r in session.run(query, id=plant_id)
            ]

            if not downstream_edges:
                print("⚠️ No downstream path found.")
                return

            print(
                f"✅ Found {len(downstream_edges)} "
                f"downstream segments."
            )

            # 4. Match Neo4j edges to GPKG
            geometry_index, river_crs = (
                self._load_river_geometry()
            )

            matched = [
                geometry_index[
                    (e["from_node"], e["to_node"])
                ]
                for e in downstream_edges
                if (e["from_node"], e["to_node"])
                in geometry_index
            ]

            print(
                f"🔗 Matched {len(matched)}/"
                f"{len(downstream_edges)} segments."
            )

            if not matched:
                print("❌ No GPKG geometry matched.")
                return

            # 5. Convert river geometry to metres
            river = (
                gpd.GeoDataFrame(
                    geometry=matched,
                    crs=river_crs,
                )
                .to_crs(METRIC_CRS)
            )

            downstream_river = river.geometry.union_all()

            # 6. Generate multiple EA search points
            #    rather than relying on one midpoint.
            spacing = max(radius_km * 1000, 100) * 2
            search_points = []

            for line in river.geometry:

                if line.length <= 0:
                    continue

                intervals = max(
                    1,
                    int(line.length / spacing),
                )

                search_points.extend(
                    line.interpolate(
                        line.length * i / intervals
                    )
                    for i in range(intervals + 1)
                )

            # Deduplicate nearby points.
            unique = {
                (round(p.x, 1), round(p.y, 1)): p
                for p in search_points
            }

            search_points = (
                gpd.GeoSeries(
                    list(unique.values()),
                    crs=METRIC_CRS,
                )
                .to_crs(WGS84)
            )

            print(
                f"📍 Using {len(search_points)} "
                f"EA search points."
            )

            # 7. Query EA and deduplicate stations
            candidates = {}

            for i, point in enumerate(
                search_points,
                1,
            ):

                stations = (
                    self.ea_client.find_nearby_stations(
                        point.y,
                        point.x,
                        distance_km=radius_km,
                    )
                )

                if stations:
                    print(
                        f"📡 Search point "
                        f"{i}/{len(search_points)} "
                        f"→ {len(stations)} station(s)"
                    )

                for station in stations:

                    station_id = station.get("station_id")

                    if station_id:
                        candidates[station_id] = station

            print(
                f"📡 EA returned "
                f"{len(candidates)} unique candidates."
            )

            if not candidates:
                print("❌ No EA stations found.")
                return

            # 8. Calculate exact distance to river geometry
            stations = []
            points = []

            for station in candidates.values():

                lat = station.get("latitude")
                lon = station.get("longitude")

                if lat is None or lon is None:
                    continue

                stations.append(station)
                points.append(Point(lon, lat))

            if not stations:
                print("❌ EA stations had no coordinates.")
                return

            points = (
                gpd.GeoSeries(
                    points,
                    crs=WGS84,
                )
                .to_crs(METRIC_CRS)
            )

            discovered = {}

            for station, point in zip(stations, points):

                distance_km = (
                    point.distance(downstream_river)
                    / 1000
                )

                if distance_km <= radius_km:

                    station["distance_km_to_path"] = round(
                        distance_km,
                        3,
                    )

                    discovered[
                        station["station_id"]
                    ] = station

            if not discovered:
                print(
                    f"❌ No stations within "
                    f"{radius_km} km of the river."
                )
                return

            stations = list(discovered.values())

            print(
                f"\n📊 Found {len(stations)} EA station(s):"
            )

            for station in stations:
                print(
                    f"   {station['station_id']} | "
                    f"{station['label']} | "
                    f"{station['watercourse_name']} | "
                    f"{station['distance_km_to_path']} km"
                )

            # 9. Store stations in Neo4j
            session.run(
                """
                UNWIND $batch AS row

                MERGE (s:MonitoringStation {
                    id: row.station_id
                })

                SET
                    s.name = row.label,
                    s.location = point({
                        latitude: toFloat(row.latitude),
                        longitude: toFloat(row.longitude)
                    }),
                    s.watercourse = row.watercourse_name,
                    s.distance_km_to_path =
                        toFloat(row.distance_km_to_path)
                """,
                batch=stations,
            )

            print(
                f"📥 Loaded {len(stations)} station(s) into Neo4j."
            )

            # 10. Fetch measurements
            print("\n📊 RECENT EA CHEMISTRY:")

            for i, station in enumerate(stations, 1):

                print(
                    f"\n[{i}] "
                    f"{station['station_id']} | "
                    f"{station['label']}"
                )

                telemetry = (
                    self.ea_client.get_station_measurements(
                        station["station_id"],
                        limit=10,
                        start_date=start_date,
                        end_date=end_date,
                    )
                )

                if not telemetry:
                    print("    No measurements available.")
                    continue

                for metric in telemetry:
                    print(
                        f"    📅 {metric['sample_time']} | "
                        f"{metric['pollutant']}: "
                        f"{metric['value']} "
                        f"{metric['unit']}"
                    )


if __name__ == "__main__":

    analyser = DownstreamImpactAnalyser()

    try:
        analyser.run_downstream_analysis(
            plant_id="WTW_way_1107212036",
            graph_depth=40,
            radius_km=1.0,
            start_date="2020-01-01",
            end_date="2026-08-31",
        )
    finally:
        analyser.close()