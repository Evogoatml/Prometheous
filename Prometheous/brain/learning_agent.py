import time, json
from adap.plugins import user_behavior                 # logs user actions1
from adap.plugins import learning_core                 # task metrics store2
from adap.plugins import neural_core                   # adaptive state core3
from adap.agent_core import audit                      # signed audit log4
from adap.plugins import memory_vault                  # encrypted vault5

VAULT_COLLECTION = "records"

def _now():
    return int(time.time())

def learn_topic(topic: str):
    topic = (topic or "").strip()
    if not topic:
        print("⚠️ No topic provided.")
        return {"status": "error", "msg": "empty topic"}

    entry = {
        "type": "learn",
        "topic": topic,
        "ts": _now()
    }

    # 1) persist securely
    idx = memory_vault.append(entry)                  # encrypted append6

    # 2) record behavior + task success
    user_behavior.record("learn_topic", "success")    # behavior log7
    learning_core.record("learn", "success", {"len": len(topic)})  # metrics8

    # 3) adaptive feedback
    neural_core.update("success")                     # adjust state9

    # 4) signed audit trail
    audit.append({"event":"learn_topic","topic":topic,"index":idx}) # signed JSON line10

    print(f"[learn] stored #{idx}: {topic}")
    return {"status": "ok", "index": idx, "topic": topic}

def list_learnings():
    data = memory_vault.load()                        # decrypt & load11
    recs = data.get("records", [])
    if not recs:
        print("No learned topics yet.")
        return []
    # pretty print list
    for i, r in enumerate(recs, 1):
        if r.get("type") == "learn":
            print(f"{i}. {r.get('topic')}  (ts={r.get('ts')})")
    return recs
