"""
seed_demo_data.py — SwaramPay demo data seeder.

Run AFTER the presenter has enrolled via a real call (not before).
Usage:  python seed_demo_data.py <presenter_phone_10_digits>

What this does:
  1. Creates recipient user records in data/users.json (bhatija, beti)
  2. Creates funded account records in data/accounts.json
  3. PATCHES the presenter's existing contacts array to include those recipients
     (does NOT touch the presenter's voice_model or any other field)

What this does NOT do:
  - Does NOT create the presenter user (they must enroll via real call first)
  - Does NOT change any voice_model fields
  - Does NOT re-run if presenter not yet enrolled (prints a warning and exits)
"""

import sys
import json
from pathlib import Path

USERS_PATH = 'data/users.json'
ACCOUNTS_PATH = 'data/accounts.json'


def load_json(path):
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def seed(presenter_phone: str):
    users = load_json(USERS_PATH)
    accounts = load_json(ACCOUNTS_PATH)

    # --- Guard: presenter must have enrolled first ---
    if presenter_phone not in users:
        print(f"❌  Presenter {presenter_phone} not found in users.json.")
        print("   Enroll via a real call first, then run this script.")
        sys.exit(1)

    presenter = users[presenter_phone]
    if not presenter.get('voice_model'):
        print(f"⚠️   Presenter {presenter_phone} has no voice_model yet (enrollment incomplete?).")
        print("   Proceeding anyway — contacts will be patched.")

    # --- Recipient 1: bhatija (Rahul Sharma) ---
    bhatija_phone = '9876543210'
    bhatija_acc_id = f'acc_{bhatija_phone}'
    if bhatija_phone not in users:
        users[bhatija_phone] = {
            'name': 'Rahul Sharma',
            'phone': bhatija_phone,
            'lang': 'hi',
            'voice_model': [],
            'account_id': bhatija_acc_id,
            'guardians': [],
            'contacts': [],
            'registered_on': '2026-01-01',
        }
        print(f"✅  Created bhatija user: {bhatija_phone} (Rahul Sharma)")
    else:
        print(f"ℹ️   bhatija user {bhatija_phone} already exists — skipping creation.")

    if bhatija_acc_id not in accounts:
        accounts[bhatija_acc_id] = {
            'balance': 5000,
            'transactions': [
                {'type': 'credit', 'amount': 5000, 'from': 'seed', 'desc': 'Demo seed', 'timestamp': '2026-01-01 00:00:00'}
            ],
        }
        print(f"✅  Created bhatija account with ₹5000 balance.")

    # --- Recipient 2: beti (Sunita Devi) ---
    beti_phone = '9988776655'
    beti_acc_id = f'acc_{beti_phone}'
    if beti_phone not in users:
        users[beti_phone] = {
            'name': 'Sunita Devi',
            'phone': beti_phone,
            'lang': 'hi',
            'voice_model': [],
            'account_id': beti_acc_id,
            'guardians': [],
            'contacts': [],
            'registered_on': '2026-01-01',
        }
        print(f"✅  Created beti user: {beti_phone} (Sunita Devi)")
    else:
        print(f"ℹ️   beti user {beti_phone} already exists — skipping creation.")

    if beti_acc_id not in accounts:
        accounts[beti_acc_id] = {
            'balance': 3000,
            'transactions': [
                {'type': 'credit', 'amount': 3000, 'from': 'seed', 'desc': 'Demo seed', 'timestamp': '2026-01-01 00:00:00'}
            ],
        }
        print(f"✅  Created beti account with ₹3000 balance.")

    # --- Patch presenter's contacts ---
    new_contacts = [
        {'nickname': 'bhatija', 'real_name': 'Rahul Sharma', 'phone': bhatija_phone},
        {'nickname': 'bhanje',  'real_name': 'Rahul Sharma', 'phone': bhatija_phone},  # oblique alias
        {'nickname': 'beti',    'real_name': 'Sunita Devi',  'phone': beti_phone},
        {'nickname': 'ladki',   'real_name': 'Sunita Devi',  'phone': beti_phone},     # alias
    ]
    existing_contacts = presenter.get('contacts', [])
    existing_phones = {c['phone'] for c in existing_contacts}
    added = 0
    for contact in new_contacts:
        if contact['phone'] not in existing_phones:
            existing_contacts.append(contact)
            existing_phones.add(contact['phone'])
            added += 1
    users[presenter_phone]['contacts'] = existing_contacts
    print(f"✅  Patched presenter {presenter_phone} contacts: +{added} new entries.")
    print(f"   Total contacts now: {len(existing_contacts)}")

    # --- Save ---
    save_json(USERS_PATH, users)
    save_json(ACCOUNTS_PATH, accounts)
    print("\n🌾 Seed complete. Demo flow ready:")
    print(f"   Presenter: {presenter_phone} ({presenter.get('name', 'unknown')})")
    print(f"   bhatija → {bhatija_phone} (Rahul Sharma, ₹5000)")
    print(f"   beti    → {beti_phone} (Sunita Devi, ₹3000)")
    print('\n   Test: "mere bhatije ko chaar sau rupaye bhejo"')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python seed_demo_data.py <presenter_phone_10_digits>")
        sys.exit(1)
    phone = sys.argv[1].strip().lstrip('+91').lstrip('+')
    if len(phone) != 10 or not phone.isdigit():
        print("❌  Phone must be a 10-digit number (no country code).")
        sys.exit(1)
    seed(phone)
