import os
from google import generativeai as genai
from google.generativeai import types
from PIL import Image


class GoogleClient:
    """A client for interacting with the Google Generative AI API."""

    def __init__(self, api_key: str):
        """Initializes the GoogleClient.

        Args:
            api_key (str): The Google API key.
        """
        self.api_key = api_key
        # Configure the library with your API key
        genai.configure(api_key=self.api_key)
        # Initialize the generative model
        self.model = genai.GenerativeModel("gemini-2.5-flash")

    def generate_content(self, contents: list, system_instruction: str = None, temperature: float = 0.1):
        """Generates content using the Google Generative AI model.

        Args:
            contents (list): A list of content parts to send to the model.
            system_instruction (str, optional): A system instruction to guide
                the model's behavior. Defaults to None.
            temperature (float, optional): The temperature for the generation.
                Defaults to 0.1.

        Returns:
            str: The generated text from the model.
        """
        generation_config = types.GenerationConfig(
            temperature=temperature
        )

        # The system_instruction is now passed as a special part of the contents
        if system_instruction:
            full_contents = [system_instruction] + contents
        else:
            full_contents = contents

        response = self.model.generate_content(
            full_contents,
            generation_config=generation_config
        )
        return response.text
