import sqlite3
conn = sqlite3.connect('pantry.db')
conn.row_factory = sqlite3.Row
print("Count-based ingredients:")
for row in conn.execute("SELECT * FROM ingredients WHERE base_unit_type = 'count' LIMIT 20"):
    print(dict(row))
conn.close()
