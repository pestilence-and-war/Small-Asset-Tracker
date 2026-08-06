import unittest
import os
import sqlite3
from app import app as flask_app
import app.database as db_mod
import app.routes as routes_mod

class BaseTestCase(unittest.TestCase):
    def setUp(self):
        # Use a separate test database
        self.db_path = 'test_pantry.db'
        flask_app.config['TESTING'] = True
        flask_app.config['DATABASE'] = self.db_path
        
        # Override get_db_connection in both modules
        self.original_db_get_conn = db_mod.get_db_connection
        self.original_routes_get_conn = routes_mod.get_db_connection
        
        db_mod.get_db_connection = self.get_test_db_connection
        routes_mod.get_db_connection = self.get_test_db_connection
        
        # Also patch it in units.py if it's imported there
        import app.units as units_mod
        self.original_units_get_conn = units_mod.get_db_connection
        units_mod.get_db_connection = self.get_test_db_connection
        
        # Initialize and seed test DB
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except PermissionError:
                pass
        db_mod.init_db()
        db_mod.seed_db()
        
        self.client = flask_app.test_client()

    def tearDown(self):
        # Restore original connection functions
        db_mod.get_db_connection = self.original_db_get_conn
        routes_mod.get_db_connection = self.original_routes_get_conn
        import app.units as units_mod
        units_mod.get_db_connection = self.original_units_get_conn
        
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except PermissionError:
                pass

    def get_test_db_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
