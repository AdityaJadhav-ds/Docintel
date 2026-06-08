import sys; sys.path.insert(0, '.')
from app.core.supabase_client import get_supabase
sb = get_supabase()

users   = sb.table('users').select('id').limit(300).execute().data or []
docs    = sb.table('documents').select('user_id,doc_type').limit(300).execute().data or []
ext     = sb.table('extracted_data').select('user_id,doc_type').limit(300).execute().data or []
reviews = sb.table('reviews').select('user_id,decision,created_at').limit(300).execute().data or []

user_ids   = [u['id'] for u in users]
has_docs   = {d['user_id'] for d in docs}
has_ext    = {e['user_id'] for e in ext}
has_review = {r['user_id'] for r in reviews}

fully_done  = has_ext & has_review
has_ext_no_review = has_ext - has_review
pending     = has_docs - has_ext

print(f'Total users:          {len(user_ids)}')
print(f'Users with docs:      {len(has_docs)}')
print(f'Extracted (done):     {len(has_ext)}')
print(f'Fully reviewed:       {len(fully_done)}')
print(f'Extracted no review:  {len(has_ext_no_review)}')
print(f'Pending (no extract): {len(pending)} {sorted(pending)[:10]}')
print()

# Pick 10: prefer unprocessed, fill with already-processed for re-run test
batch_10 = sorted(pending)[:10]
if len(batch_10) < 10:
    already = sorted(fully_done)[:10-len(batch_10)]
    batch_10 += already
print(f'Proposed 10-user batch: {batch_10}')

# Identify 1 already-processed user for text-refresh verification
rerun_target = sorted(fully_done)[0] if fully_done else None
print(f'Re-run target (stale text test): user_id={rerun_target}')
if rerun_target:
    user_ext = [e for e in ext if e['user_id'] == rerun_target]
    for e in user_ext:
        print('  existing: doc_type=' + str(e['doc_type']) + ' updated_at=' + str(e['updated_at']))
