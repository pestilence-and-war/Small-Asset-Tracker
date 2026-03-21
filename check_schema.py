import sqlite3
conn = sqlite3.connect('pantry.db')
cursor = conn.execute("SELECT sql FROM sqlite_master WHERE name='ingredient_conversions'")
print(cursor.fetchone()[0])
conn.close()
