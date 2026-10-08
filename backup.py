import os
import sqlite3
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "mood_journal.db")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
KEEP = 14  # 残す世代数

os.makedirs(BACKUP_DIR, exist_ok=True)
dest = os.path.join(BACKUP_DIR, f"mood_journal_{datetime.now():%Y%m%d_%H%M%S}.db")

src = sqlite3.connect(DB_PATH)
dst = sqlite3.connect(dest)
with dst:
    src.backup(dst)
dst.close()
src.close()

# 古いものを削除
files = sorted(f for f in os.listdir(BACKUP_DIR) if f.endswith(".db"))
for old in files[:-KEEP]:
    os.remove(os.path.join(BACKUP_DIR, old))

print("バックアップ完了:", dest)