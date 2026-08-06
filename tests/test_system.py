from tests.base import BaseTestCase
import json

class TestSystem(BaseTestCase):
    def test_pantry_flow(self):
        # 1. Add ingredient via manual entry
        response = self.client.post('/add_ingredient', data={
            'q': 'Flour',
            'quantity': '500',
            'unit': 'g'
        })
        self.assertEqual(response.status_code, 200)
        
        # 2. Verify it's in the pantry
        response = self.client.get('/pantry')
        self.assertIn(b'flour', response.data)
        
        # 3. Update quantity
        # First get the ID
        conn = self.get_test_db_connection()
        ing_id = conn.execute("SELECT id FROM ingredients WHERE name = 'flour'").fetchone()['id']
        conn.close()
        
        response = self.client.post('/update_quantity', data={
            'id': ing_id,
            'change': '250',
            'unit': 'g'
        })
        self.assertEqual(response.status_code, 200)
        
        # 4. Verify total is 750
        response = self.client.get('/pantry')
        self.assertIn(b'750.00', response.data)

    def test_recipe_flow(self):
        # 1. Create ingredient
        self.client.post('/add_ingredient', data={'q': 'Pasta', 'quantity': '1', 'unit': 'kg'})
        
        # 2. Create meal
        response = self.client.post('/add_meal', data={'meal_name': 'Spaghetti'})
        self.assertEqual(response.status_code, 200)
        
        # 3. Add ingredient to meal
        conn = self.get_test_db_connection()
        meal_id = conn.execute("SELECT id FROM meals WHERE name = 'spaghetti'").fetchone()['id']
        conn.close()
        
        response = self.client.post(f'/add_ingredient_to_meal/{meal_id}', data={
            'q': 'pasta',
            'quantity': '200',
            'unit': 'g'
        })
        self.assertEqual(response.status_code, 200)
        
        # 4. Verify recipe details
        response = self.client.get(f'/recipe/{meal_id}')
        self.assertIn(b'pasta', response.data)
        self.assertIn(b'200', response.data)

    def test_cooking_session_deduction(self):
        # 1. Setup pantry
        self.client.post('/add_ingredient', data={'q': 'Pasta', 'quantity': '1', 'unit': 'kg'})
        conn = self.get_test_db_connection()
        ing_id = conn.execute("SELECT id FROM ingredients WHERE name = 'pasta'").fetchone()['id']
        conn.close()
        
        # 2. Setup recipe
        self.client.post('/add_meal', data={'meal_name': 'Spaghetti'})
        conn = self.get_test_db_connection()
        meal_id = conn.execute("SELECT id FROM meals WHERE name = 'spaghetti'").fetchone()['id']
        conn.close()
        self.client.post(f'/add_ingredient_to_meal/{meal_id}', data={'q': 'pasta', 'quantity': '200', 'unit': 'g'})
        
        # 3. Start cooking session and update pantry
        response = self.client.post('/update_pantry', data={
            'recipe_items_used': [str(ing_id)],
            f'ingredient_id_to_deduct_for_{ing_id}': str(ing_id),
            f'ingredient_qty_for_{ing_id}': '200',
            f'ingredient_unit_for_{ing_id}': 'g'
        })
        self.assertEqual(response.status_code, 200)
        
        # 4. Verify deduction (1000 - 200 = 800)
        conn = self.get_test_db_connection()
        qty = conn.execute("SELECT quantity FROM ingredients WHERE id = ?", (ing_id,)).fetchone()['quantity']
        self.assertEqual(qty, 800)
        conn.close()

    def test_data_view(self):
        # 1. Setup some data
        self.client.post('/add_ingredient', data={'q': 'Carrot', 'quantity': '5', 'unit': 'unit'})
        
        # 2. Access data view
        response = self.client.get('/data')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'carrot', response.data)
        self.assertIn(b'System Data Explorer', response.data)
