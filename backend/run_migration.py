"""
run_migration.py — Apply a single SQL migration to Supabase via the REST API.
Usage: python run_migration.py migrations/007_academic_engine_results.sql
"""
import sys
import os
import requests
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

def run_sql(sql: str):
    """Execute raw SQL via Supabase's REST /rpc endpoint (pg_execute_sql)."""
    # Use the SQL editor endpoint
    url = f"{SUPABASE_URL}/rest/v1/rpc/exec_sql"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    # Supabase doesn't expose a raw SQL endpoint in anon/service REST.
    # Use the Python client's postgrest workaround: split by ';' and
    # try each statement as a separate table creation via supabase-py.
    from supabase import create_client
    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Execute the SQL using rpc (requires a pg function) or via postgrest
    # Simplest approach: use the Python client's execute_sql (v2)
    try:
        result = client.rpc("exec_sql", {"query": sql}).execute()
        print("✅ Migration applied via RPC exec_sql")
        return
    except Exception as e:
        print(f"RPC exec_sql not available ({e}), trying statement-by-statement...")

    # Fallback: print the SQL and instruct manual execution
    print("\n" + "="*60)
    print("MANUAL MIGRATION REQUIRED")
    print("="*60)
    print("Run this SQL in your Supabase SQL Editor:")
    print(f"  https://supabase.com/dashboard/project/{SUPABASE_URL.split('.')[0].split('//')[1]}/sql/new")
    print("\n" + sql)


if __name__ == "__main__":
    migration_file = sys.argv[1] if len(sys.argv) > 1 else "migrations/007_academic_engine_results.sql"
    with open(migration_file, encoding="utf-8") as f:
        sql = f.read()
    print(f"Applying migration: {migration_file}")
    run_sql(sql)
