import os
import sys
from dotenv import load_dotenv

# Add the app directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.importer_service import import_recipe_from_text

# Load environment variables from .env file
load_dotenv()

def run_test():
    # Check if the API key is set
    if not os.getenv("GOOGLE_API_KEY") or os.getenv("GOOGLE_API_KEY") == "your_api_key_here":
        print("SKIPPING TEST: GOOGLE_API_KEY is not set in the .env file.")
        print("Please create a .env file and add your Google API key to run this test.")
        return

    print("Testing recipe import with Gemini...")

    # Sample recipe text
    recipe_text = """
    Spaghetti Carbonara

    Ingredients:
    - 200g spaghetti
    - 100g pancetta
    - 2 large eggs
    - 50g pecorino cheese
    - Salt and black pepper to taste

    Instructions:
    1. Cook the spaghetti in salted boiling water.
    2. While the pasta is cooking, fry the pancetta in a pan.
    3. In a separate bowl, whisk the eggs and cheese together.
    4. Drain the pasta and add it to the pan with the pancetta.
    5. Remove the pan from the heat and stir in the egg and cheese mixture.
    6. Season with salt and pepper and serve immediately.
    """

    # Call the import function
    parsed_recipe = import_recipe_from_text(recipe_text)

    # Print the result
    print("Parsed Recipe:")
    print(parsed_recipe)

    # Assertions to verify the result
    assert isinstance(parsed_recipe, dict), "The result should be a dictionary."
    assert "recipe_name" in parsed_recipe, "The recipe name should be present."
    assert "ingredients" in parsed_recipe, "The ingredients should be present."
    assert "instructions" in parsed_recipe, "The instructions should be present."
    assert isinstance(parsed_recipe["ingredients"], list), "Ingredients should be a list."
    assert len(parsed_recipe["ingredients"]) > 0, "There should be at least one ingredient."
    assert "quantity" in parsed_recipe["ingredients"][0], "Ingredient should have a quantity."
    assert "unit" in parsed_recipe["ingredients"][0], "Ingredient should have a unit."
    assert "name" in parsed_recipe["ingredients"][0], "Ingredient should have a name."

    print("\nTest passed successfully!")

if __name__ == "__main__":
    run_test()
