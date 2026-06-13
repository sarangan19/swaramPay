import json

def load_json(path):
    try:
        with open(path, 'r') as f: return json.load(f)
    except: return {}

def get_user(phone):
    users = load_json('data/users.json')
    return users.get(phone)

def get_account(acc_id):
    accounts = load_json('data/accounts.json')
    return accounts.get(acc_id)