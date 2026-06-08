import os
import sys

# Ensure backend dir is in PYTHONPATH so app imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.supabase_client import get_supabase
from app.services.validation_service import process_user_documents

def main():
    print("Fetching users with documents...")
    sb = get_supabase()
    res = sb.table("documents").select("user_id").execute()
    docs = res.data or []
    
    user_ids = list(set(d["user_id"] for d in docs))
    print(f"Found {len(user_ids)} users with uploaded documents.")
    
    success_count = 0
    fail_count = 0
    
    for uid in user_ids:
        print(f"Processing user ID: {uid}...")
        try:
            result = process_user_documents(uid)
            print(f"  -> SUCCESS! Overall Status: {result.get('summary', {}).get('overall_status', 'UNKNOWN')}")
            success_count += 1
        except Exception as e:
            print(f"  -> FAILED: {e}")
            fail_count += 1
            
    print(f"\nReprocessing Complete!")
    print(f"Success: {success_count} | Failed: {fail_count}")

if __name__ == "__main__":
    main()
