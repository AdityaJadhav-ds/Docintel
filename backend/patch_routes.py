"""Patch list_users to add final_aadhaar/final_pan fields explicitly."""
import re

with open('app/api/routes.py', encoding='utf-8') as f:
    content = f.read()

# Find the enriched_user dict block — between entered_pan_number and doc_types lines
old_block = (
    '                # \u2500\u2500 USER-ENTERED IDs (from the upload form, stored in users table) \u2500\u2500\n'
    '                "entered_aadhaar_number": u.get("aadhaar_number") or "",\n'
    '                "entered_pan_number":     u.get("pan_number")     or "",\n'
    '                # \u2500\u2500 CONTACT FIELDS \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n'
    '                "email":             u.get("email") or "",\n'
    '                "mobile_number":     u.get("mobile_number") or "",\n'
    '                "permanent_address": u.get("permanent_address") or "",\n'
    '                # \u2500\u2500 Display name: final_name if verified, else full_name \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n'
)

new_block = (
    '                # \u2500\u2500 USER-ENTERED IDs (from the upload form, stored in users table) \u2500\u2500\n'
    '                "entered_aadhaar_number": u.get("aadhaar_number") or "",\n'
    '                "entered_pan_number":     u.get("pan_number")     or "",\n'
    '                # \u2500\u2500 FINAL VERIFIED values: explicit (Supabase omits null columns) \u2500\u2500\n'
    '                "final_name":    u.get("final_name")    or None,\n'
    '                "final_aadhaar": u.get("final_aadhaar") or None,\n'
    '                "final_pan":     u.get("final_pan")     or None,\n'
    '                "final_dob":     u.get("final_dob")     or None,\n'
    '                # Flat display fields: final_* wins; OCR/entered is fallback\n'
    '                "aadhaar_number": u.get("final_aadhaar") or a.get("aadhaar_number") or u.get("aadhaar_number") or "",\n'
    '                "pan_number":     u.get("final_pan")     or p.get("pan_number")     or u.get("pan_number")     or "",\n'
    '                # \u2500\u2500 CONTACT FIELDS \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n'
    '                "email":             u.get("email") or "",\n'
    '                "mobile_number":     u.get("mobile_number") or "",\n'
    '                "permanent_address": u.get("permanent_address") or "",\n'
    '                # \u2500\u2500 Display name: final_name if verified, else full_name \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n'
)

if old_block in content:
    content = content.replace(old_block, new_block, 1)
    with open('app/api/routes.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('SUCCESS: final_aadhaar/final_pan added to list_users enriched output')
else:
    print('BLOCK NOT FOUND - trying partial match...')
    idx = content.find('"entered_pan_number":     u.get("pan_number")')
    print(f'entered_pan_number found at char index: {idx}')
    if idx >= 0:
        print(repr(content[idx-200:idx+400]))
