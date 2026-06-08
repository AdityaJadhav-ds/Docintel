import time
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.core.supabase_client import get_supabase

def run():
    sb = get_supabase()
    
    t0 = time.time()
    users_res = sb.table("users").select("id").execute()
    t1 = time.time()
    print(f"Users fetch: {t1-t0:.2f}s")
    
    user_ids = [u["id"] for u in users_res.data]
    print(f"Total users: {len(user_ids)}")
    
    t2 = time.time()
    ext_res = sb.table("extracted_data").select("user_id").in_("user_id", user_ids).execute()
    t3 = time.time()
    print(f"Extracted data fetch: {t3-t2:.2f}s")
    
    t4 = time.time()
    docs_res = sb.table("documents").select("user_id").in_("user_id", user_ids).execute()
    t5 = time.time()
    print(f"Documents fetch: {t5-t4:.2f}s")
    
    t6 = time.time()
    rv_res = sb.table("validation_reviews").select("user_id").execute()
    t7 = time.time()
    print(f"Validation reviews fetch: {t7-t6:.2f}s")
    
if __name__ == '__main__':
    run()
