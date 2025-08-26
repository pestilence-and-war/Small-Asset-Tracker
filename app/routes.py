from flask import render_template, request
from app import app
from app.database import get_db_connection

def get_all_ingredients():
    conn = get_db_connection()
    ingredients = conn.execute('SELECT * FROM ingredients ORDER BY name').fetchall()
    conn.close()
    return ingredients

def get_all_meals():
    conn = get_db_connection()
    meals = conn.execute('SELECT * FROM meals ORDER BY name').fetchall()
    conn.close()
    return meals

@app.route('/')
def index():
    ingredients = get_all_ingredients()
    meals = get_all_meals()
    return render_template('index.html', ingredients=ingredients, meals=meals)

@app.route('/add_ingredient', methods=['POST'])
def add_ingredient():
    ingredient_name = request.form['ingredient_name'].strip().lower()
    quantity = request.form.get('quantity', 0)
    unit = request.form.get('unit', '')

    if ingredient_name:
        conn = get_db_connection()
        try:
            conn.execute(
                'INSERT INTO ingredients (name, quantity, unit) VALUES (?, ?, ?) ON CONFLICT(name) DO UPDATE SET quantity = quantity + excluded.quantity',
                (ingredient_name, quantity, unit)
            )
            conn.commit()
        except conn.IntegrityError as e:
            # This should ideally not happen with the ON CONFLICT clause, but as a fallback
            print(f"Error adding ingredient: {e}")
            pass
        finally:
            conn.close()

    ingredients = get_all_ingredients()
    return render_template('_ingredients_list.html', ingredients=ingredients)

@app.route('/search')
def search():
    query = request.args.get('q', '').strip().lower()
    conn = get_db_connection()
    if query:
        ingredients = conn.execute(
            "SELECT * FROM ingredients WHERE name LIKE ? ORDER BY name LIMIT 5",
            (query + '%',)
        ).fetchall()
    else:
        ingredients = []
    conn.close()
    return render_template('_search_results.html', ingredients=ingredients)

@app.route('/update_quantity', methods=['POST'])
def update_quantity():
    ingredient_id = request.form['id']
    change = float(request.form['change'])

    conn = get_db_connection()
    conn.execute(
        "UPDATE ingredients SET quantity = quantity + ? WHERE id = ?",
        (change, ingredient_id)
    )
    conn.commit()

    # Fetch the updated ingredient to send back
    ingredient = conn.execute("SELECT * FROM ingredients WHERE id = ?", (ingredient_id,)).fetchone()
    conn.close()

    return render_template('_ingredient_item.html', ingredient=ingredient)

@app.route('/deduct_meal', methods=['POST'])
def deduct_meal():
    meal_id = request.form.get('meal_id')
    portion = float(request.form.get('portion', 1.0))

    if not meal_id:
        # Handle error: no meal selected
        ingredients = get_all_ingredients()
        return render_template('_ingredients_list.html', ingredients=ingredients)

    conn = get_db_connection()
    # Get ingredients for the meal
    meal_ingredients = conn.execute("""
        SELECT ingredient_id, quantity FROM meal_ingredients WHERE meal_id = ?
    """, (meal_id,)).fetchall()

    # Deduct each ingredient
    for item in meal_ingredients:
        required_quantity = item['quantity'] * portion
        conn.execute(
            "UPDATE ingredients SET quantity = quantity - ? WHERE id = ?",
            (required_quantity, item['ingredient_id'])
        )

    conn.commit()
    conn.close()

    # Return the updated ingredient list
    ingredients = get_all_ingredients()
    return render_template('_ingredients_list.html', ingredients=ingredients)
