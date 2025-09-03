import json
import os
from app.api_clients.google_client import GoogleClient
from dotenv import load_dotenv
from PIL import Image

load_dotenv()


def _parse_recipe_from_llm_response(response_text: str) -> dict:
    """Cleans and parses a JSON string from the model's response.

    This function searches for a JSON object within the raw text response,
    extracts it, and parses it into a Python dictionary.

    Args:
        response_text (str): The raw text response from the language model.

    Returns:
        dict: A dictionary containing the parsed recipe data, or an empty
            dictionary if parsing fails.
    """
    try:
        # Find the start and end of the JSON object
        start_index = response_text.find('{')
        end_index = response_text.rfind('}')

        if start_index == -1 or end_index == -1 or end_index < start_index:
            print("Error: Could not find a valid JSON object in the response.")
            print(f"Raw response was: {response_text}")
            return {}

        # Extract the JSON string
        json_str = response_text[start_index:end_index+1]

        # Parse the JSON
        data = json.loads(json_str)

        # Basic validation
        if "recipe_name" in data and "ingredients" in data and "instructions" in data:
            return data
        else:
            print("Error: Parsed JSON is missing required keys.")
            return {}
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON from model response: {e}")
        print(f"Raw response was: {response_text}")
        return {}
    except Exception as e:
        print(f"An unexpected error occurred during parsing: {e}")
        return {}


def import_recipe_from_text(text: str) -> dict:
    """Uses the Google API to extract recipe data from a block of text.

    Args:
        text (str): A string containing the recipe.

    Returns:
        dict: A dictionary containing the extracted recipe data, or an empty
            dictionary if an error occurs.
    """
    prompt = f"""
    You are a recipe parsing assistant. Your task is to extract the recipe name,
    a list of ingredients (with quantity, unit, and name), and the instructions
    from the provided text. If an ingredient has a qualifier that is not a common spice
    name (e.g., minced onion), only include the item name.
    If you encounter mixed fractions, include them as-is.
    The base unit for quantity is "unit" (example: when the recipe calls for 1 lemon).
    Return the output as a single, valid JSON object. Do not include any explanatory
    text or markdown formatting before or after the JSON object.

    The JSON object should have the following structure:
    {{
      "recipe_name": "string",
      "ingredients": [
        {{
          "quantity": "string",
          "unit": "string",
          "name": "string"
        }}
      ],
      "instructions": "string"
    }}

    Here is the recipe text:
    ---
    {text}
    ---
    """
    try:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            print("Error: GOOGLE_API_KEY not found in environment variables.")
            return {}

        client = GoogleClient(api_key=api_key)
        response_text = client.generate_content(
            contents=[prompt],
            temperature=0.1
        )

        return _parse_recipe_from_llm_response(response_text)

    except Exception as e:
        print(f"An unexpected error occurred during API call: {e}")
        return {}


def import_recipe_from_image(image_path: str) -> dict:
    """Uses the Google API with vision capabilities to extract recipe data from an image.

    Args:
        image_path (str): The file path to the recipe image.

    Returns:
        dict: A dictionary containing the extracted recipe data, or an empty
            dictionary if an error occurs.
    """
    prompt = """
    You are a recipe parsing assistant. Your task is to analyze the provided image,
    which contains a recipe, and extract the recipe name, a list of ingredients
    (with quantity, unit, and name), and the instructions.
    Return the output as a single, valid JSON object. Do not include any explanatory
    text or markdown formatting before or after the JSON object.

    The JSON object should have the following structure:
    {
      "recipe_name": "string",
      "ingredients": [
        {
          "quantity": "string",
          "unit": "string",
          "name": "string"
        }
      ],
      "instructions": "string"
    }
    """
    try:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            print("Error: GOOGLE_API_KEY not found in environment variables.")
            return {}

        if not os.path.exists(image_path):
            print(f"Error: Image file not found at {image_path}")
            return {}

        client = GoogleClient(api_key=api_key)
        image = Image.open(image_path)

        response_text = client.generate_content(
            contents=[image, prompt],
            temperature=0.1
        )

        return _parse_recipe_from_llm_response(response_text)

    except Exception as e:
        print(f"An unexpected error occurred during image import: {e}")
        return {}
