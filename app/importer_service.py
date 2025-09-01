import ollama
import json

def import_recipe_from_text(text: str) -> dict:
    """
    Uses a multi-modal model to extract recipe data from a block of text.

    Args:
        text: A string containing the recipe.

    Returns:
        A dictionary with the extracted recipe data, conforming to a specific JSON schema.
        Returns an empty dictionary if parsing fails.
    """
    prompt = f"""
    You are a recipe parsing assistant. Your task is to extract the recipe name,
    a list of ingredients (with quantity, unit, and name), and the instructions
    from the provided text.
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
        # It's a good practice to check if the model is available.
        # For this implementation, we assume 'gemma3:4b' is running.
        # A more robust solution might involve checking available models.
        response = ollama.chat(
            model='gemma3:4b',
            messages=[{'role': 'user', 'content': prompt}],
            options={'temperature': 0.1} # Lower temperature for more deterministic output
        )

        # The response content should be the JSON string.
        response_text = response['message']['content']

        # Clean up the response to get only the JSON part.
        # Models sometimes add markdown backticks around the JSON.
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]

        response_text = response_text.strip()

        # Parse the JSON string into a Python dictionary.
        data = json.loads(response_text)

        # Basic validation of the structure
        if "recipe_name" in data and "ingredients" in data and "instructions" in data:
            return data
        else:
            print("Error: Parsed JSON is missing required keys.")
            return {{}}

    except json.JSONDecodeError as e:
        print(f"Error decoding JSON from model response: {e}")
        print(f"Raw response was: {response['message']['content']}")
        return {{}}
    except Exception as e:
        print(f"An unexpected error occurred while calling the Ollama API: {e}")
        return {{}}
