"""
probe_extracted_data.py — check extracted_data table schema and constraints
"""
import os, sys
sys.path.insert(0, '.')
os.chdir(r'Z:\doc-validator 2\doc-validator\backend')
from dotenv import load_dotenv
load_dotenv('.env')
from supabase import create_client
sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY'])

# Check extracted_data table
print('=== extracted_data table ===')
try:
    res = sb.table('extracted_data').select('*').limit(2).execute()
    print('columns:', list(res.data[0].keys()) if res.data else 'empty')
    print('rows:', res.data[:2])
except Exception as e:
    print('ERROR:', str(e)[:200])

# Try inserting a probe with doc_type='tenth' into extracted_data
print()
print('=== Probe: insert tenth into extracted_data ===')
try:
    users = sb.table('users').select('id').limit(1).execute()
    uid = users.data[0]['id']
    result = sb.table('extracted_data').insert({
        'user_id': uid,
        'doc_type': 'tenth',
        'version': 9999,
        'name': '_probe_',
        'confidence_score': 0.0,
    }).execute()
    if result.data:
        pid = result.data[0]['id']
        sb.table('extracted_data').delete().eq('id', pid).execute()
        print(f'SUCCESS - extracted_data accepts doc_type=tenth! (probe_id={pid}, cleaned up)')
    else:
        print('No data returned')
except Exception as e:
    print('FAILED:', str(e)[:300])

# Check documents table for the CHECK constraint name
print()
print('=== Check if documents has unique constraint on (user_id, doc_type, version) ===')
try:
    # Try inserting duplicate to see what constraints exist
    users = sb.table('users').select('id').limit(1).execute()
    uid = users.data[0]['id']
    # Try inserting aadhaar to see duplicate handling
    result = sb.table('documents').insert({
        'user_id': uid,
        'doc_type': 'aadhaar',
        'version': 9999,
        'storage_path': '_probe_aadhaar_',
    }).execute()
    if result.data:
        pid = result.data[0]['id']
        sb.table('documents').delete().eq('id', pid).execute()
        print(f'documents accepts aadhaar v9999 probe - cleaned up id={pid}')
except Exception as e:
    print('documents probe error:', str(e)[:200])
