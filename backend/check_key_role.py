"""
create_academic_table.py
========================
Creates the academic_documents table and fixes all wiring.
Uses Supabase service role to create the table via REST.
"""
import os, sys
sys.path.insert(0, '.')
os.chdir(r'Z:\doc-validator 2\doc-validator\backend')

from dotenv import load_dotenv
load_dotenv('.env')

from supabase import create_client
sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY'])

# === Test if we can create tables ===
print('=== Testing table creation capability ===')

# Try creating a simple test table
try:
    # Supabase REST (PostgREST) cannot run DDL.
    # BUT we can insert into a table that doesn't have a CHECK constraint.
    # Strategy: create academic_documents table via supabase-py
    # by using the management API or direct postgres.
    
    # First check if we have a service_role token
    import jwt
    try:
        decoded = jwt.decode(os.environ['SUPABASE_KEY'], options={"verify_signature": False})
        role = decoded.get('role', 'unknown')
        print(f'JWT role: {role}')
        print(f'JWT claims: {decoded}')
    except Exception as e:
        print(f'JWT decode error: {e}')
        # Try without pyjwt
        import base64
        parts = os.environ['SUPABASE_KEY'].split('.')
        if len(parts) == 3:
            padded = parts[1] + '=' * (4 - len(parts[1]) % 4)
            import json
            payload = json.loads(base64.urlsafe_b64decode(padded))
            print(f'JWT payload: {payload}')
            role = payload.get('role', 'unknown')
            print(f'Key role: {role}')
        else:
            print(f'Key format: {os.environ["SUPABASE_KEY"][:30]}...')
            role = 'unknown'

except Exception as e:
    print(f'Error: {e}')
    role = 'unknown'

print(f'\nRole detected: {role}')
if role == 'service_role':
    print('Service role key - can bypass RLS but still cannot run DDL via REST')
    print('Need to use pg_net or direct postgres connection for DDL')
elif role == 'anon':
    print('Anon key - cannot run DDL')
else:
    print(f'Unknown role: {role}')
