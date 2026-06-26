import sqlite3

DB = "btc_recovery.db"
conn = sqlite3.connect(DB)

# Use 2GB RAM cache
conn.execute("PRAGMA cache_size = -2000000")
# Store temp tables in memory
conn.execute("PRAGMA temp_store = MEMORY")
# Memory-map 4GB
conn.execute("PRAGMA mmap_size = 4000000000")
# WAL mode for concurrent reads
conn.execute("PRAGMA journal_mode = WAL")
# Faster writes (safe for recovery use)
conn.execute("PRAGMA synchronous = NORMAL")

conn.commit()
print("DB optimized for 32GB RAM")

# Show current stats
total = conn.execute("SELECT COUNT(*) FROM addresses").fetchone()[0]
scanned = conn.execute("SELECT COUNT(*) FROM scan").fetchone()[0]
hits = conn.execute("SELECT COUNT(*) FROM scan WHERE balance_sat > 0").fetchone()[0]
print(f"Addresses: {total} | Scanned: {scanned} | With balance: {hits}")
conn.close()
