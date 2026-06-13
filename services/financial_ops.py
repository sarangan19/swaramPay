import json

def load_json(path):
    try:
        with open(path, 'r') as f: return json.load(f)
    except: return {}

def save_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

def calculate_behavioral_score(user_phone):
    users = load_json('data/users.json')
    accounts = load_json('data/accounts.json')
    transactions = load_json('data/transactions.json')
    
    user = users.get(user_phone)
    if not user: return 300, ["No data"]
    
    acc_id = user.get('account_id')
    txns = transactions.get(acc_id, [])
    acc = accounts.get(acc_id, {})
    
    # Base score
    score = 300
    factors = []
    
    # 1. Platform Usage (Transaction Volume)
    if len(txns) > 5:
        score += 150
        factors.append("High transaction volume")
    elif len(txns) > 0:
        score += 50
        factors.append("Active transaction history")
        
    # 2. Savings Consistency
    savings_bal = acc.get('balance', 0)
    if savings_bal > 10000:
        score += 200
        factors.append("Strong savings balance")
    elif savings_bal > 2000:
        score += 100
        factors.append("Moderate savings balance")
        
    # 3. Timely repayment & PF (Mocked signals)
    pf_bal = acc.get('pf', 0)
    if pf_bal > 0:
        score += 150
        factors.append("Formal employment & PF contribution")
        
    # Cap score
    score = min(score, 900)
    
    return score, factors

def perform_upi_transaction(user_phone, amount):
    amount = float(amount)
    users = load_json('data/users.json')
    accounts = load_json('data/accounts.json')
    txns = load_json('data/transactions.json')
    
    user = users.get(user_phone)
    acc_id = user.get('account_id')
    
    if accounts[acc_id]['balance'] >= amount:
        accounts[acc_id]['balance'] -= amount
        
        # Initialize the transaction list if it doesn't exist yet
        if acc_id not in txns:
            txns[acc_id] = []
            
        txns[acc_id].append({"type": "debit", "amount": amount, "desc": "UPI Payment"})
        
        save_json('data/accounts.json', accounts)
        save_json('data/transactions.json', txns)
        return True, accounts[acc_id]['balance']
    return False, accounts[acc_id]['balance']
