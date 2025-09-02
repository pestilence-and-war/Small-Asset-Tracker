import os
from google import generativeai as genai
from google.generativeai import types
from PIL import Image

class GoogleClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = genai.Client(api_key=self.api_key)

    def generate_content(self, contents: list, system_instruction: str = None, temperature: float = 0.1):
        model = "gemini-1.5-flash"

        config = types.GenerateContentConfig(
            temperature=temperature
        )

        if system_instruction:
            config.system_instruction = system_instruction

        response = self.client.models.generate_content(
            model=model,
            contents=contents,
            config=config
        )
        return response.text
