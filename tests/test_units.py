from tests.base import BaseTestCase
from app.units import convert_to_base, convert_units, parse_quantity, parse_quantity_and_unit
from app.database import get_db_connection

class TestUnits(BaseTestCase):
    def test_parse_quantity(self):
        self.assertEqual(parse_quantity("1.5"), 1.5)
        self.assertEqual(parse_quantity("1/2"), 0.5)
        self.assertEqual(parse_quantity("1 1/2"), 1.5)
        with self.assertRaises(ValueError):
            parse_quantity("not a number")

    def test_parse_quantity_and_unit(self):
        self.assertEqual(parse_quantity_and_unit("500 g"), (500, "g"))
        self.assertEqual(parse_quantity_and_unit("1.5 cup diced"), (1.5, "cup diced"))
        self.assertEqual(parse_quantity_and_unit("10oz"), (10, "oz"))

    def test_standard_conversions(self):
        # 1 kg = 1000 g
        qty, unit, unit_type = convert_to_base(1, "kg")
        self.assertEqual(qty, 1000)
        self.assertEqual(unit, "g")
        self.assertEqual(unit_type, "mass")

        # 1 cup = 236.588 ml
        qty, unit, unit_type = convert_to_base(1, "cup")
        self.assertAlmostEqual(qty, 236.588, places=3)
        self.assertEqual(unit, "ml")
        self.assertEqual(unit_type, "volume")

    def test_density_conversion(self):
        # Create an ingredient with density
        conn = get_test_db_connection_standalone()
        conn.execute("INSERT INTO ingredients (name, quantity, base_unit, base_unit_type, density_g_ml) VALUES (?, ?, ?, ?, ?)",
                     ("oil", 0, "ml", "volume", 0.92))
        conn.commit()
        
        # Fetch ID
        ing_id = conn.execute("SELECT id FROM ingredients WHERE name = 'oil'").fetchone()['id']
        
        # 100g of oil should be ~108.7ml
        qty, unit, unit_type = convert_to_base(100, "g", ingredient_id=ing_id, conn=conn)
        self.assertEqual(unit, "ml")
        self.assertAlmostEqual(qty, 100 / 0.92, places=3)
        conn.close()

    def test_custom_conversions(self):
        conn = get_test_db_connection_standalone()
        conn.execute("INSERT INTO ingredients (name, quantity, base_unit, base_unit_type) VALUES (?, ?, ?, ?)",
                     ("egg", 0, "unit", "count"))
        conn.commit()
        ing_id = conn.execute("SELECT id FROM ingredients WHERE name = 'egg'").fetchone()['id']
        
        # Add custom rule: 1 egg = 50 g
        conn.execute("INSERT INTO ingredient_conversions (ingredient_id, from_unit, to_unit, factor) VALUES (?, ?, ?, ?)",
                     (ing_id, "unit", "g", 50))
        conn.commit()
        
        # 2 eggs should be 100g
        res = convert_units(2, "unit", "g", ingredient_id=ing_id, conn=conn)
        self.assertEqual(res, 100)
        
        # 100g should be 2 eggs
        res = convert_units(100, "g", "unit", ingredient_id=ing_id, conn=conn)
        self.assertEqual(res, 2)
        conn.close()

def get_test_db_connection_standalone():
    conn = sqlite3.connect('test_pantry.db')
    conn.row_factory = sqlite3.Row
    return conn

import sqlite3
