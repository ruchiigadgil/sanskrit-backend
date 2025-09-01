import sys
from pathlib import Path
import os
root_path = str(Path(__file__).resolve().parent.parent)
sys.path.append(root_path)
print("Python path:", sys.path)
print("Root directory:", root_path)
print("Current working directory:", os.getcwd())

try:
    from Database.db import get_db_connection
    print("Import successful!")
    db = get_db_connection()
    print("Database connection:", db)
except Exception as e:
    print("Import failed:", str(e))