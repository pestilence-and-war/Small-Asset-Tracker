import os
import io
import ollama
from PIL import Image

class OllamaClient:
    """A client for interacting with the Ollama local model API."""

    def __init__(self, api_key: str = None, model: str = None):
        """Initializes the OllamaClient.

        Args:
            api_key (str, optional): Ignored. Included for compatibility with GoogleClient interface.
            model (str, optional): The Ollama model name to use. Defaults to 'gemma4:26b'.
        """
        self.model = model or os.getenv("OLLAMA_MODEL", "gemma4:26b")
        # Initialize the client. OLLAMA_HOST env var is automatically respected by ollama package,
        # but we can explicitly pass it if present.
        host = os.getenv("OLLAMA_HOST")
        self.client = ollama.Client(host=host)

    def generate_content(self, contents: list, system_instruction: str = None, temperature: float = 0.1):
        """Generates content using the Ollama model.

        Args:
            contents (list): A list of content parts (strings or PIL Image objects) to send to the model.
            system_instruction (str, optional): A system instruction to guide
                the model's behavior. Defaults to None.
            temperature (float, optional): The temperature for the generation.
                Defaults to 0.1.

        Returns:
            str: The generated text from the model.
        """
        images = []
        text_parts = []

        for item in contents:
            if isinstance(item, Image.Image):
                # Convert PIL Image to bytes
                img_byte_arr = io.BytesIO()
                # Determine format or fallback to JPEG
                img_format = item.format or 'JPEG'
                item.save(img_byte_arr, format=img_format)
                images.append(img_byte_arr.getvalue())
            elif isinstance(item, str):
                text_parts.append(item)
            else:
                text_parts.append(str(item))

        prompt = "\n".join(text_parts)

        messages = []
        if system_instruction:
            messages.append({
                'role': 'system',
                'content': system_instruction
            })

        user_message = {
            'role': 'user',
            'content': prompt
        }
        if images:
            user_message['images'] = images

        messages.append(user_message)

        response = self.client.chat(
            model=self.model,
            messages=messages,
            options={
                'temperature': temperature
            }
        )
        return response['message']['content']
