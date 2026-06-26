import sqlite3

class Memory:
    def __init__(self, path="data/brain.db"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS memory (user_id TEXT, input TEXT, output TEXT)"
        )
        self.conn.commit()

    def save(self, user_id, inp, out):
        self.conn.execute(
            "INSERT INTO memory (user_id, input, output) VALUES (?,?,?)",
            (str(user_id), inp, out),
        )
        self.conn.commit()
        
    def get_history(self, user_id, limit=10):
        cursor = self.conn.execute(
            "SELECT input, output FROM memory WHERE user_id=? ORDER BY ROWID DESC LIMIT ?",
            (str(user_id), limit)
        )
        return cursor.fetchall()
