
import json, os, time
FILE = 'adap/data/user_behavior.json'

def record(command, result):
    os.makedirs(os.path.dirname(FILE), exist_ok=True)
    data = load()
    data.append({'command': command, 'result': result, 'time': time.time()})
    with open(FILE, 'w') as f:
        json.dump(data, f, indent=2)

def load():
    if os.path.exists(FILE):
        with open(FILE) as f:
            return json.load(f)
    return []

def suggest():
    data = load()
    if not data:
        return 'No suggestions yet.'
    freq = {}
    for d in data:
        freq[d['command']] = freq.get(d['command'],0)+1
    top = max(freq, key=freq.get)
    return f'You often run: {top}'
