import json
import os
import threading
from app.api_clients.google_client import GoogleClient
from dotenv import load_dotenv

load_dotenv()

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
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            print("Error: GOOGLE_API_KEY not found in environment variables.")
            return {{}}

        client = GoogleClient(api_key=api_key)

        messages = [{{'role': 'user', 'content': prompt}}]
        config = {{
            "model": "gemini-1.5-flash",
            "temperature": 0.1,
        }}
        stop_event = threading.Event()

        response_generator = client.send_message_stream_yield(messages, config, stop_event)

        response_text = ""
        for event, data in response_generator:
            if event == "chunk":
                response_text += data
            elif event == "finish":
                # The 'finish' event in this implementation contains the full accumulated text
                response_text = data
                break
            elif event == "error":
                print(f"Error from Google API: {{data}}")
                return {{}}

        # Clean up the response to get only the JSON part.
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
        print(f"Error decoding JSON from model response: {{e}}")
        print(f"Raw response was: {{response_text}}")
        return {{}}
    except Exception as e:
        print(f"An unexpected error occurred: {{e}}")
        return {{}}
