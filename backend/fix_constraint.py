"""
fix_constraint.py
=================
Fixes the documents table CHECK constraint to allow academic doc types.
Run with: python fix_constraint.py
"""

import os
import sys
import json
import urllib.request
import urllib.error
import ssl

# ── Config ──────────────────────────────────────────────────────────────────
PROJECT_REF = os.environ.get("SUPABASE_PROJECT_REF", "ymzuecxzgvamlbqhlnqs")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")  # Set in .env — never hardcode secrets
BASE_URL    = f"https://{PROJECT_REF}.supabase.co"

HEADERS = {
    "Content-Type":  "application/json",
    "Authorization": f"Bearer {SERVICE_KEY}",
    "apikey":        SERVICE_KEY,
}

# ── Approach 1: Try the Supabase Management API SQL endpoint ─────────────────
def try_management_api():
    """Try https://api.supabase.com/v1/projects/{ref}/database/query"""
    sql = (
        "ALTER TABLE public.documents "
        "DROP CONSTRAINT IF EXISTS documents_doc_type_check; "
        "ALTER TABLE public.documents "
        "ADD CONSTRAINT documents_doc_type_check "
        "CHECK (doc_type IN ('aadhaar','pan','tenth','twelfth','diploma','degree','semester'));"
    )
    url = f"https://api.supabase.com/v1/projects/{PROJECT_REF}/database/query"
    payload = json.dumps({"query": sql}).encode()
    req = urllib.request.Request(url, data=payload, method="POST")
    for k, v in HEADERS.items():
        req.add_header(k, v)
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
            body = resp.read().decode()
            print(f"[Management API] Status {resp.status}: {body[:300]}")
            return True
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"[Management API] HTTP {e.code}: {body[:300]}")
        return False
    except Exception as e:
        print(f"[Management API] Error: {e}")
        return False


# ── Approach 2: Create a PostgreSQL function via Supabase REST, then call it ─
def try_create_and_call_rpc():
    """
    Use service role to:
    1. CREATE a temporary stored procedure that runs the DDL
    2. CALL it via RPC
    3. DROP it
    This works if the service role has SUPERUSER or can CREATE FUNCTIONS.
    """
    ctx = ssl.create_default_context()

    # The function body (DDL inside a plpgsql function)
    create_fn_sql = """
    CREATE OR REPLACE FUNCTION public._fix_doc_type_constraint()
    RETURNS void
    LANGUAGE plpgsql
    SECURITY DEFINER
    AS $$
    BEGIN
      ALTER TABLE public.documents
        DROP CONSTRAINT IF EXISTS documents_doc_type_check;
      ALTER TABLE public.documents
        ADD CONSTRAINT documents_doc_type_check
        CHECK (doc_type IN ('aadhaar','pan','tenth','twelfth','diploma','degree','semester'));
    END;
    $$;
    """

    # We can't send raw DDL through supabase-py REST, but we CAN call an RPC
    # if the function exists. The trick: use the Supabase SQL endpoint.
    # Supabase's REST API (PostgREST) doesn't support raw DDL — we need
    # the pg_net extension or a direct psql connection.

    # Try psycopg2 with the Supabase pooler
    try:
        import psycopg2
        # Standard Supabase pooler connection string format
        # Password is the same as the API key for service role in newer Supabase versions
        # Or it's set during project creation
        conn_strings = [
            f"postgresql://postgres.{PROJECT_REF}:{SERVICE_KEY}@aws-0-ap-south-1.pooler.supabase.com:6543/postgres",
            f"postgresql://postgres.{PROJECT_REF}:{SERVICE_KEY}@aws-0-us-east-1.pooler.supabase.com:6543/postgres",
            f"postgresql://postgres:{SERVICE_KEY}@db.{PROJECT_REF}.supabase.co:5432/postgres",
        ]
        for conn_str in conn_strings:
            try:
                print(f"[psycopg2] Trying: {conn_str[:80]}...")
                conn = psycopg2.connect(conn_str, connect_timeout=10, sslmode="require")
                conn.autocommit = True
                cur = conn.cursor()
                cur.execute("ALTER TABLE public.documents DROP CONSTRAINT IF EXISTS documents_doc_type_check")
                cur.execute(
                    "ALTER TABLE public.documents ADD CONSTRAINT documents_doc_type_check "
                    "CHECK (doc_type IN ('aadhaar','pan','tenth','twelfth','diploma','degree','semester'))"
                )
                cur.close()
                conn.close()
                print("[psycopg2] ✅ Constraint fixed successfully!")
                return True
            except Exception as e:
                print(f"[psycopg2] Connection failed: {e}")
        return False
    except ImportError:
        print("[psycopg2] Not installed")
        return False


# ── Approach 3: Verify the fix worked ───────────────────────────────────────
def verify_fix():
    """Try inserting a probe row with doc_type='tenth'"""
    from supabase import create_client
    sb = create_client(BASE_URL, SERVICE_KEY)

    users = sb.table("users").select("id").limit(1).execute()
    if not users.data:
        print("[verify] No users found — cannot test probe insert")
        return False

    uid = users.data[0]["id"]
    try:
        result = sb.table("documents").insert({
            "user_id":      uid,
            "doc_type":     "tenth",
            "version":      9999,
            "storage_path": "_probe_fix_constraint_DELETE_ME",
        }).execute()
        if result.data:
            probe_id = result.data[0]["id"]
            sb.table("documents").delete().eq("id", probe_id).execute()
            print(f"[verify] ✅ CONSTRAINT FIXED! 'tenth' INSERT succeeded (probe_id={probe_id}, cleaned up)")
            return True
        else:
            print("[verify] INSERT returned no data")
            return False
    except Exception as e:
        print(f"[verify] ❌ STILL BROKEN: {e}")
        return False


# ── Approach 4: Patch via Supabase Edge Function trick ──────────────────────
def patch_via_supabase_rpc():
    """
    Last resort: call a known Supabase admin endpoint to run SQL.
    Supabase has a /pg endpoint in some versions.
    """
    ctx = ssl.create_default_context()

    sqls = [
        "ALTER TABLE public.documents DROP CONSTRAINT IF EXISTS documents_doc_type_check",
        "ALTER TABLE public.documents ADD CONSTRAINT documents_doc_type_check CHECK (doc_type IN ('aadhaar','pan','tenth','twelfth','diploma','degree','semester'))",
    ]

    for sql in sqls:
        url = f"{BASE_URL}/rest/v1/rpc/exec"
        payload = json.dumps({"sql": sql}).encode()
        req = urllib.request.Request(url, data=payload, method="POST")
        for k, v in HEADERS.items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
                print(f"[RPC exec] OK: {sql[:60]}")
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            print(f"[RPC exec] {e.code}: {body[:200]}")
        except Exception as e:
            print(f"[RPC exec] {e}")


# ── MAIN ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("DocValidator — Fix Academic Storage Constraint")
    print("=" * 60)

    print("\n[1/4] Verifying current state (should FAIL)...")
    already_fixed = verify_fix()

    if already_fixed:
        print("\n✅ Constraint is already correct! No fix needed.")
        sys.exit(0)

    print("\n[2/4] Trying Management API...")
    ok = try_management_api()

    if not ok:
        print("\n[3/4] Trying psycopg2 direct connection...")
        ok = try_create_and_call_rpc()

    if not ok:
        print("\n[4/4] Trying RPC exec...")
        patch_via_supabase_rpc()

    print("\n[Verify] Testing if fix worked...")
    fixed = verify_fix()

    if fixed:
        print("\n🎉 SUCCESS — Academic documents can now be saved to the database!")
        print("Restart your backend and try uploading academic docs again.")
    else:
        print()
        print("=" * 60)
        print("MANUAL ACTION REQUIRED")
        print("=" * 60)
        print("None of the automated methods could apply the DDL.")
        print("You MUST run this SQL in Supabase Dashboard → SQL Editor:")
        print()
        print("  ALTER TABLE public.documents")
        print("    DROP CONSTRAINT IF EXISTS documents_doc_type_check;")
        print()
        print("  ALTER TABLE public.documents")
        print("    ADD CONSTRAINT documents_doc_type_check")
        print("    CHECK (doc_type IN (")
        print("      'aadhaar', 'pan',")
        print("      'tenth', 'twelfth', 'diploma', 'degree', 'semester'")
        print("    ));")
        print()
        print("URL: https://supabase.com/dashboard/project/ymzuecxzgvamlbqhlnqs/sql/new")
        sys.exit(1)
