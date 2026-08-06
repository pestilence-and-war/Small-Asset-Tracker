from tests.base import BaseTestCase
from app.units import convert_to_base, convert_units
from app.routes import generate_shopping_list
import sqlite3

class TestInheritance(BaseTestCase):
    def test_density_inheritance(self):
        conn = self.get_test_db_connection()
        # Create Parent: Onion with density
        conn.execute("INSERT INTO ingredients (name, category, quantity, base_unit, base_unit_type, density_g_ml) VALUES (?, ?, ?, ?, ?, ?)",
                     ("onion", "other", 0, "g", "mass", 0.53)) # Approx density of chopped onion
        parent_id = conn.execute("SELECT id FROM ingredients WHERE name = 'onion'").fetchone()['id']
        
        # Create Child: Red Onion without density
        conn.execute("INSERT INTO ingredients (name, category, quantity, base_unit, base_unit_type, parent_id) VALUES (?, ?, ?, ?, ?, ?)",
                     ("red onion", "other", 0, "g", "mass", parent_id))
        child_id = conn.execute("SELECT id FROM ingredients WHERE name = 'red onion'").fetchone()['id']
        conn.commit()
        
        # 1 cup of red onion should use parent density (0.53 g/ml)
        # 236.588 ml * 0.53 g/ml = 125.39 g
        qty, unit, unit_type = convert_to_base(1, "cup", ingredient_id=child_id, conn=conn)
        self.assertAlmostEqual(qty, 236.588 * 0.53, places=2)
        conn.close()

    def test_conversion_rule_inheritance(self):
        conn = self.get_test_db_connection()
        # Create Parent: Egg
        conn.execute("INSERT INTO ingredients (name, quantity, base_unit, base_unit_type) VALUES (?, ?, ?, ?)",
                     ("egg", 0, "unit", "count"))
        parent_id = conn.execute("SELECT id FROM ingredients WHERE name = 'egg'").fetchone()['id']
        
        # Add custom rule to parent: 1 egg = 50 g
        conn.execute("INSERT INTO ingredient_conversions (ingredient_id, from_unit, to_unit, factor) VALUES (?, ?, ?, ?)",
                     (parent_id, "unit", "g", 50))
        
        # Create Child: Large Egg
        conn.execute("INSERT INTO ingredients (name, quantity, base_unit, base_unit_type, parent_id) VALUES (?, ?, ?, ?, ?)",
                     ("large egg", 0, "unit", "count", parent_id))
        child_id = conn.execute("SELECT id FROM ingredients WHERE name = 'large egg'").fetchone()['id']
        conn.commit()
        
        # Large Egg should inherit "1 egg = 50 g" rule
        res = convert_units(2, "unit", "g", ingredient_id=child_id, conn=conn)
        self.assertEqual(res, 100)
        conn.close()

    def test_stock_aggregation(self):
        conn = self.get_test_db_connection()
        # Create Parent: Cheese (100g)
        conn.execute("INSERT INTO ingredients (name, category, quantity, base_unit, base_unit_type) VALUES (?, ?, ?, ?, ?)",
                     ("cheese", "other", 100, "g", "mass"))
        parent_id = conn.execute("SELECT id FROM ingredients WHERE name = 'cheese'").fetchone()['id']
        
        # Create Child: Cheddar (200g)
        conn.execute("INSERT INTO ingredients (name, category, quantity, base_unit, base_unit_type, parent_id) VALUES (?, ?, ?, ?, ?, ?)",
                     ("cheddar", "other", 200, "g", "mass", parent_id))
        
        # Create a meal plan needing 400g of Cheese
        conn.execute("INSERT INTO meal_plans (name) VALUES ('test_plan')")
        plan_id = conn.execute("SELECT id FROM meal_plans WHERE name = 'test_plan'").fetchone()['id']
        
        conn.execute("INSERT INTO meals (name) VALUES ('Mac n Cheese')")
        meal_id = conn.execute("SELECT id FROM meals WHERE name = 'Mac n Cheese'").fetchone()['id']
        
        conn.execute("INSERT INTO meal_ingredients (meal_id, ingredient_id, quantity, unit) VALUES (?, ?, ?, ?)",
                     (meal_id, parent_id, 400, "g"))
        
        conn.execute("INSERT INTO meal_plan_items (meal_plan_id, meal_id, multiplier) VALUES (?, ?, ?)",
                     (plan_id, meal_id, 1.0))
        conn.commit()
        
        # Shopping list should show we need 100g more cheese (400 required - (100 parent + 200 child))
        shopping_list = generate_shopping_list(plan_id)
        
        cheese_list = shopping_list.get("other", [])
        self.assertEqual(len(cheese_list), 1)
        self.assertEqual(cheese_list[0]['name'], "cheese")
        self.assertEqual(cheese_list[0]['quantity'], 100) # 400 - 300
        conn.close()
