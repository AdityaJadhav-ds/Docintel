"""probe_tables.py — enumerate DB tables and check schemas"""
import os, sys
sys.path.insert(0, '.')
os.chdir(r'Z:\doc-validator 2\doc-validator\backend')

from dotenv import load_dotenv
load_dotenv('.env')

from supabase import create_client
sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY'])

# Check academic_documents table
print('=== academic_documents ===')
try:
    res = sb.table('academic_documents').select('*').limit(3).execute()
    print(f'EXISTS! rows={len(res.data)}')
    if res.data:
        print('columns:', list(res.data[0].keys()))
    else:
        # Try inserting probe to see what columns are required
        # Instead, let's just describe the known structure from migration 004
        print('empty table - columns from migration 004: id, doc_type, confidence, extracted, warnings, raw_text, status, created_at')
        print('MISSING: candidate_id / user_id (migration 005 was supposed to add these)')
except Exception as e:
    print('ERROR:', str(e)[:200])

# Check users table
print()
print('=== users ===')
try:
    res = sb.table('users').select('*').limit(1).execute()
    print('columns:', list(res.data[0].keys()) if res.data else 'empty')
except Exception as e:
    print('ERROR:', str(e)[:200])

# Check documents table columns by successful select
print()
print('=== documents (existing rows) ===')
try:
    res = sb.table('documents').select('*').limit(2).execute()
    print('columns:', list(res.data[0].keys()) if res.data else 'empty')
    print('sample rows:')
    for r in res.data[:2]:
        print(' ', r)
except Exception as e:
    print('ERROR:', str(e)[:200])

# Check the constraint on documents
print()
print('=== documents doc_type distinct values ===')
try:
    res = sb.table('documents').select('doc_type').execute()
    types = set(r['doc_type'] for r in (res.data or []))
    print('existing doc_types:', types)
except Exception as e:
    print('ERROR:', str(e)[:200])

# Test other table names
print()
print('=== Other table checks ===')
for t in ['academic_records', 'academic_docs', 'candidates']:
    try:
        res = sb.table(t).select('id').limit(1).execute()
        print(f'{t}: EXISTS, data={res.data}')
    except Exception as e:
        msg = str(e)
        if 'schema cache' in msg.lower() or 'not exist' in msg.lower() or 'PGRST205' in msg:
            print(f'{t}: DOES NOT EXIST')
        else:
            print(f'{t}: error: {msg[:100]}')
