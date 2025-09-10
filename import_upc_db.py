import sqlite3
import json

def import_data():
    """Reads UPC data from a JSONL file and imports it into the SQLite database."""
    db_path = 'pantry.db'
    jsonl_path = 'upc_database.jsonl'

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Create the upc_data table if it doesn't exist.
        # Using UPC as the PRIMARY KEY ensures uniqueness and creates an index automatically.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS upc_data (
                upc TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                quantity REAL,
                unit TEXT
            )
        ''')

        print(f"Importing data from {jsonl_path} into {db_path}...")

        # Read the JSONL file and insert data.
        with open(jsonl_path, 'r') as f:
            for line in f:
                try:
                    data = json.loads(line)
                    # Use INSERT OR REPLACE to handle re-running the script.
                    cursor.execute(
                        "INSERT OR REPLACE INTO upc_data (upc, name, quantity, unit) VALUES (?, ?, ?, ?)",
                        (data['upc'], data['name'], data.get('quantity'), data.get('unit'))
                    )
                except json.JSONDecodeError:
                    print(f"Warning: Could not decode line: {line.strip()}")
                except KeyError:
                    print(f"Warning: Missing required key in line: {line.strip()}")

        conn.commit()
        print("Import complete.")

        # Verify by counting rows
        count = cursor.execute("SELECT COUNT(*) FROM upc_data").fetchone()[0]
        print(f"The 'upc_data' table now contains {count} records.")

    except FileNotFoundError:
        print(f"Error: The file '{jsonl_path}' was not found.")
    except Exception as e:
        print(f"An error occurred: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    import_data()
