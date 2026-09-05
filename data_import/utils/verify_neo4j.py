"""
Quick verification of Neo4j graph: kiểm tra nodes + relationships.
Run: cd data_import && python verify_neo4j.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from dotenv import load_dotenv
from neo4j import GraphDatabase


def main() -> None:
    base = Path(__file__).resolve().parent
    for p in [base / ".env", base.parent / "backend" / ".env"]:
        if p.exists():
            load_dotenv(p, override=False)

    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USERNAME")
    pwd = os.getenv("NEO4J_PASSWORD")
    db = os.getenv("NEO4J_DATABASE", "neo4j")

    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    try:
        with driver.session(database=db) as session:
            print("=" * 60)
            print("NODE COUNTS")
            print("=" * 60)
            for row in session.run("""
                MATCH (n)
                RETURN labels(n)[0] AS label, count(n) AS n
                ORDER BY n DESC
            """):
                print(f"  {row['label']:12s} {row['n']}")

            print()
            print("=" * 60)
            print("STRUCTURE EDGES")
            print("=" * 60)
            for row in session.run("""
                MATCH ()-[r]->()
                WHERE type(r) STARTS WITH 'HAS_'
                RETURN type(r) AS t, count(r) AS n
                ORDER BY n DESC
            """):
                print(f"  {row['t']:15s} {row['n']}")

            print()
            print("=" * 60)
            print("RELATIONSHIP EDGES (2 directions)")
            print("=" * 60)
            for row in session.run("""
                MATCH ()-[r]->()
                WHERE type(r) IN ['AMENDS','ADDS','REPLACES','REPEALS',
                                  'AMENDED_BY','ADDED_IN','REPLACED_BY','REPEALED_BY']
                RETURN type(r) AS t, count(r) AS n
                ORDER BY t
            """):
                print(f"  {row['t']:15s} {row['n']}")

            print()
            print("=" * 60)
            print("SAMPLE RELATIONSHIPS (D238 -> D168)")
            print("=" * 60)
            for row in session.run("""
                MATCH (src)-[r]->(tgt)
                WHERE type(r) IN ['AMENDS','ADDS','REPLACES','REPEALS']
                RETURN src.id AS src_id, type(r) AS rel, tgt.id AS tgt_id,
                       r.reason AS reason
                LIMIT 10
            """):
                print(f"  ({row['src_id']}) -[{row['rel']}]-> ({row['tgt_id']})")
                print(f"    reason: {row['reason']}")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
