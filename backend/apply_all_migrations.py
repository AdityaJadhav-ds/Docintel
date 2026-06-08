"""
apply_all_migrations.py — Apply pending schema migrations to Supabase.
Usage: venv/Scripts/python apply_all_migrations.py
"""
import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

# All DDL statements — idempotent, safe to run multiple times
MIGRATIONS = [
    # 008 — verification status fields
    "ALTER TABLE public.users ADD COLUMN IF NOT EXISTS is_verified int DEFAULT 0",
    "ALTER TABLE public.users ADD COLUMN IF NOT EXISTS verification_status text DEFAULT 'PENDING'",
    "ALTER TABLE public.users ADD COLUMN IF NOT EXISTS workflow_state text DEFAULT 'UPLOADED'",
    "ALTER TABLE public.users ADD COLUMN IF NOT EXISTS status text DEFAULT 'PENDING'",
    "ALTER TABLE public.users ADD COLUMN IF NOT EXISTS review_status text",
    "ALTER TABLE public.users ADD COLUMN IF NOT EXISTS verified_at timestamptz",
    "ALTER TABLE public.users ADD COLUMN IF NOT EXISTS verified_by text",
    # 009 — contact + academic inputs
    "ALTER TABLE public.users ADD COLUMN IF NOT EXISTS email text",
    "ALTER TABLE public.users ADD COLUMN IF NOT EXISTS mobile_number text",
    "ALTER TABLE public.users ADD COLUMN IF NOT EXISTS permanent_address text",
    "ALTER TABLE public.users ADD COLUMN IF NOT EXISTS academic_inputs jsonb DEFAULT '{}'",
    # 010 — permanent approval final values
    "ALTER TABLE public.users ADD COLUMN IF NOT EXISTS final_verified boolean DEFAULT false",
    "ALTER TABLE public.users ADD COLUMN IF NOT EXISTS final_name text",
    "ALTER TABLE public.users ADD COLUMN IF NOT EXISTS final_aadhaar text",
    "ALTER TABLE public.users ADD COLUMN IF NOT EXISTS final_pan text",
    "ALTER TABLE public.users ADD COLUMN IF NOT EXISTS final_dob text",
    "ALTER TABLE public.users ADD COLUMN IF NOT EXISTS final_percentage text",
    "ALTER TABLE public.users ADD COLUMN IF NOT EXISTS final_cgpa text",
    # 011 — real-time verification locking and dirty state tracking
    "ALTER TABLE public.users ADD COLUMN IF NOT EXISTS final_verified_data jsonb DEFAULT '{}'",
    "ALTER TABLE public.users ADD COLUMN IF NOT EXISTS verification_locked boolean DEFAULT false",
]


def run_via_rpc(client, sql):
    try:
        client.rpc("exec_sql", {"query": sql}).execute()
        return True
    except Exception:
        return False


def run_via_rest(sql):
    url = f"{SUPABASE_URL}/rest/v1/rpc/exec_sql"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(url, json={"query": sql}, headers=headers, timeout=15)
        return resp.status_code in (200, 204)
    except Exception:
        return False


def apply_all():
    print("\n" + "="*60)
    print("DocValidator - Applying pending migrations to Supabase")
    print("="*60 + "\n")

    from supabase import create_client
    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    failed = []
    for i, stmt in enumerate(MIGRATIONS, 1):
        short = stmt[:70]
        ok = run_via_rpc(client, stmt) or run_via_rest(stmt)
        status = "OK  " if ok else "FAIL"
        print(f"  [{i:02d}] [{status}]  {short}...")
        if not ok:
            failed.append(stmt)

    if failed:
        print("\n" + "="*60)
        print(f"WARNING: {len(failed)} statement(s) could NOT be auto-applied.")
        print("MANUALLY run this SQL in Supabase Dashboard > SQL Editor:")
        print(f"  https://supabase.com/dashboard/project/_/sql/new\n")
        for s in failed:
            print(f"  {s};")
        print("="*60)
    else:
        print(f"\nAll {len(MIGRATIONS)} migration statements applied successfully!\n")

    # Verify
    print("Verifying users table columns...")
    try:
        from app.core.supabase_client import get_supabase
        sb = get_supabase()
        rows = sb.table("users").select("*").limit(1).execute().data
        if rows:
            cols = list(rows[0].keys())
            need = ["is_verified", "workflow_state", "status", "verification_status",
                    "final_verified", "final_name", "final_pan", "email"]
            missing = [c for c in need if c not in cols]
            if missing:
                print(f"  MISSING columns: {missing}")
                print("  --> Please run the SQL above manually in Supabase SQL Editor.")
            else:
                print(f"  All required columns present.")
                print(f"  Full column list: {cols}")
        else:
            print("  (No rows in users table yet)")
    except Exception as e:
        print(f"  Verification error: {e}")


if __name__ == "__main__":
    apply_all()
