import threading
import google.generativeai as genai
from google.generativeai import types as genai_types
from google.protobuf import json_format # Needed for args conversion
import os
import time
import json
import inspect
from .base_client import BaseApiClient
from typing import List, Dict, Any, Tuple, Generator, Callable
import logging
from google.ai.generativelanguage import Schema, Type
import copy


# Helper to convert various Part types to a serializable dict for logging/history
def part_to_dict(part):
    if hasattr(part, 'text'):
        return {'text': part.text}
    if hasattr(part, 'inline_data'):
        return {'inline_data': {'mime_type': part.inline_data.mime_type, 'data_preview': f'<bytes len={len(part.inline_data.data)}>'}}
    if hasattr(part, 'function_call'):
        args_dict = {}
        try:
            if hasattr(part.function_call.args, '_pb'):
                args_dict = json_format.MessageToDict(part.function_call.args._pb)
            else:
                args_dict = dict(part.function_call.args)
        except Exception:
             args_dict = {"error": "Could not serialize args"}
        return {'function_call': {'name': part.function_call.name, 'args': args_dict}}
    if hasattr(part, 'function_response'):
        # FunctionResponse content is already a dict/primitive
        return {'function_response': {'name': part.function_response.name, 'response': part.function_response.response}}
    return {'unknown_part': str(part)}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def _translate_schema_dict_in_place(generic_schema_dict: dict):
    """
    Recursively walks a dictionary and replaces string types with Google Type enums.
    This function modifies the dictionary that is passed to it.
    """
    # A mapping from generic JSON schema types to the required Google Enum
    type_map = {
        "string": "STRING",
        "integer": "INTEGER",
        "number": "NUMBER",  # For float and other numeric types
        "boolean": "BOOLEAN",
        "array": "ARRAY",
        "object": "OBJECT",
    }

    # Translate the type of the current schema level
    if 'type' in generic_schema_dict:
        schema_type_str = generic_schema_dict['type'].lower()
        generic_schema_dict['type'] = type_map.get(schema_type_str, "TYPE_UNSPECIFIED")

    # Recurse into nested properties for object types
    if 'properties' in generic_schema_dict:
        for key, value_dict in generic_schema_dict['properties'].items():
            _translate_schema_dict_in_place(value_dict)

    # Recurse into the 'items' definition for array types
    if 'items' in generic_schema_dict:
        _translate_schema_dict_in_place(generic_schema_dict['items'])

class GoogleClient(BaseApiClient):
    # Use models from your original list
    DEFAULT_MODELS = [
        "gemini-1.5-pro",
        "gemini-1.5-flash",
        "gemini-2.0-flash",
        "gemini-pro"
    ]

    def __init__(self, api_key: str):
        super().__init__(api_key)
        self.client = None # Client is initialized within methods now for generate_content
        try:
            # Configure the library globally

            self.client = genai.Client(api_key=api_key)
            self._check_connection()
            logger.info("Google GenAI SDK configured successfully.")
        except Exception as e:
            logger.error(f"Failed to configure Google GenAI SDK: {e}", exc_info=True)
            # Consider raising or setting an error state
            self.initialization_error = str(e) # Store error
            # raise ConnectionError(f"Failed to configure Google GenAI SDK: {e}") from e

    def _check_connection(self):
        """Attempts a basic API call using the initialized client."""
        if not self.client:
             self.initialization_error = "Client object not created."
             logger.error("Cannot check connection, client object is None.")
             return False
        try:
            # Use the client instance to list models
            list(self.client.models.list())
            logger.info("Google API connection check successful (listed models).")
            self.initialization_error = None # Clear error on success
            return True
        except Exception as e:
            logger.warning(f"Google API connection check failed: {e}")
            self.initialization_error = f"Connection Check Failed: {e}"
            return False

    def format_tool_schema(self, name: str, description: str, parameters: Dict[str, Any]) -> genai_types.FunctionDeclaration:
        """
        Builds a Google-native FunctionDeclaration by first preparing the entire
        parameter dictionary and then constructing the Schema object from it.
        """
        try:
            google_formatted_parameters = None
            if parameters and parameters.get("properties"):
                # 1. Make a deep copy to avoid changing the original tool definition
                params_copy = copy.deepcopy(parameters)

                # 2. Translate the entire dictionary structure in-place
                _translate_schema_dict_in_place(params_copy)

                # 3. Construct the Schema object from the fully prepared dictionary.
                #    The Google library will handle the nested object creation.
                google_formatted_parameters = genai_types.Schema(**params_copy)

            # Build the final tool definition object
            func_decl = genai_types.FunctionDeclaration(
                name=name,
                description=description,
                parameters=google_formatted_parameters
            )
            return func_decl
        except Exception as e:
            logger.error(f"Error formatting tool schema for '{name}': {e}", exc_info=True)
            # Re-raise the exception to be caught by the connection logic
            raise

    # --- Model Listing (Using your verified original function) ---
    def list_available_models_from_api(self) -> list:
        try:
            available_models = []
            logger.info("Attempting to fetch available models from Google API...")
            if not self.client: logger.error("Google client not initialized."); return self.DEFAULT_MODELS
            fetched_models = self.client.models.list()
            # logger.debug(f"Raw models fetched: {list(self.client.models.list())}") # Debugging consumes iterator

            for m in fetched_models: # Iterate directly
                supported_methods = getattr(m, 'supported_generation_methods', [])
                supported_actions = getattr(m, 'supported_actions', []) # Keep check for future proofing

                if "generateContent" in supported_methods or "generateContent" in supported_actions:
                    model_id = m.name.split('/')[-1]
                    if model_id not in available_models: available_models.append(model_id)
            if not available_models: logger.warning("No models supporting generateContent found."); return self.DEFAULT_MODELS
            logger.info(f"Available models fetched from API: {available_models}")
            return available_models # Return unsorted as per original
        except Exception as e:
            logger.warning(f"Could not fetch models from API, using defaults: {e}", exc_info=True)
            return self.DEFAULT_MODELS

    def get_available_models(self) -> list:
        return self.list_available_models_from_api()
    # --- End Model Listing ---

    # --- Content Preparation ---
    def _prepare_google_contents(self, messages: List[Dict[str, Any]], instance=None) -> Tuple[List[Dict[str, Any]], str | None]:
        """
        Prepares messages in the list-of-dictionaries format for generate_content's 'contents'.
        Handles roles, files, and tool calls/responses correctly using Parts.
        Returns the contents list and a potential system instruction string.
        """
        google_contents = []
        system_instruction_text = None
        temp_file_paths = [] # Keep track of temp files created for upload

        for i, msg in enumerate(messages):
            role = msg.get("role")
            content_text = msg.get("content", "") # Text part of the message
            # Use the message's 'parts' if it exists (from previous API response), otherwise build from text/files
            parts_data = msg.get("parts", []) # This field might be added by previous API calls

            # If parts aren't pre-defined, build them
            if not parts_data:
                current_parts = []
                # Add text part if content exists
                if content_text:
                    current_parts.append(genai_types.Part(text=content_text))

                # --- Attach Files (Original User Uploads or from History) ---
                files_to_process = []
                # If it's the *last* message AND a *user* message, use latest uploads if available
                if role == "user" and i == len(messages) - 1 and instance and hasattr(instance, '_latest_uploaded_files'):
                     files_to_process = getattr(instance, '_latest_uploaded_files', [])
                     # Clear after processing once per user turn submission
                     if files_to_process:
                        setattr(instance, '_latest_uploaded_files', [])
                # Or, if it's a historical message with file references
                elif msg.get("files"):
                     files_to_process = msg.get("files", [])

                if files_to_process:
                     if not content_text and not current_parts: # Add placeholder if only files
                          current_parts.append(genai_types.Part(text="[Files Attached]"))

                     for f_info in files_to_process:
                         # f_info should be a dict like {'path': ..., 'mimetype': ...}
                         file_path = f_info.get('path')
                         mime_type = f_info.get('mimetype', 'application/octet-stream')
                         if file_path and os.path.exists(file_path):
                             try:
                                 # Use file upload API for larger/persistent files if needed in future
                                 # For now, read bytes directly (suitable for moderate sizes)
                                 with open(file_path, 'rb') as file_obj:
                                     file_bytes = file_obj.read()
                                 # Google SDK handles PIL Images directly, others need bytes/Blob
                                 current_parts.append(genai_types.Part(inline_data=genai_types.Blob(mime_type=mime_type, data=file_bytes)))
                                 logger.info(f"Prepared file {file_path} ({mime_type}) as inline_data Part.")
                             except Exception as e:
                                 logger.error(f"Error reading/preparing file {file_path}: {e}")
                         else:
                             logger.warning(f"File path invalid or not found in message: {file_path}")

                parts_data = current_parts # Use the newly built parts list

            # --- Handle System Prompt ---
            if role == "system":
                if system_instruction_text is None: system_instruction_text = ""
                # Extract text from parts if structure is complex
                sys_text = content_text
                if not sys_text and parts_data:
                     sys_text = " ".join([p.text for p in parts_data if hasattr(p, 'text')])
                system_instruction_text += sys_text + "\n"
                continue # System instructions handled separately

            # --- Determine Google Role ---
            google_role = "user" if role == "user" else "model" # Treat assistant/tool as 'model'

            # --- Reconstruct Parts for Tool Calls/Responses if needed ---
            # This part adapts pre-formatted messages (like from history) into SDK objects
            final_parts_for_turn = []
            if role == "tool":
                tool_name = msg.get("name")
                result_content = msg.get("content") # Result string (usually JSON)
                if tool_name and result_content is not None:
                    try: response_data = json.loads(result_content)
                    except (json.JSONDecodeError, TypeError): response_data = {"result": result_content}
                    try:
                         final_parts_for_turn.append(genai_types.Part.from_function_response(
                            name=tool_name, response=response_data
                         ))
                         google_role = "user" # Function results are sent with role 'user'
                    except Exception as e: logger.error(f"Error creating func response part: {e}"); continue
                else: logger.warning(f"Skipping invalid tool msg: {msg}"); continue

            elif role == "assistant" and msg.get("tool_calls"):
                 if content_text: # Include preceding text if any
                      final_parts_for_turn.append(genai_types.Part(text=content_text))
                 for tool_call in msg.get("tool_calls", []):
                     fc_name = tool_call.get("name")
                     fc_args = tool_call.get("arguments", {})
                     if fc_name:
                          try:
                              function_call_obj = genai_types.FunctionCall(name=fc_name, args=fc_args)
                              final_parts_for_turn.append(genai_types.Part(function_call=function_call_obj))
                          except Exception as e: logger.error(f"Error creating func call part: {e}"); continue
                     else: logger.warning(f"Skipping tool call missing name: {tool_call}")

            else: # Regular user/assistant message or parts already processed
                 final_parts_for_turn = parts_data # Use parts built earlier from text/files

            # --- Add the complete turn to the contents list ---
            if final_parts_for_turn:
                # API expects list of dicts: [{'role': ..., 'parts': [Part, Part,...]}, ...]
                 google_contents.append({"role": google_role, "parts": final_parts_for_turn})
            elif role != "system":
                 logger.warning(f"Skipping message turn with no parts generated: {msg}")


        return google_contents, system_instruction_text.strip() if system_instruction_text else None


    # --- Main Send Method ---
    def send_message_stream_yield(self,
                                messages: List[Dict[str, Any]],
                                config: Dict[str, Any],
                                stop_event: threading.Event,
                                instance=None
                                ) -> Generator[Tuple[str, Any], None, None]:
        model_name = config.get("model")
        if not model_name: yield ("error", "No model specified."); return

        # Check client initialization status
        if not self.client or self.initialization_error:
             # Attempt to re-initialize or check connection again
             if not self._check_connection():
                  error_msg = self.initialization_error or "Google Client not initialized."
                  yield ("error", f"Client Error: {error_msg}"); return

        # --- Prepare Configs (Generation, Safety, Tools) ---
        # Consolidate optional parameters into the config object
        api_config_obj = genai_types.GenerateContentConfig(
            candidate_count=1,
            **{k: v for k, v in { # Filter None values
                "temperature": config.get("temperature"), "top_p": config.get("top_p"),
                "top_k": config.get("top_k"), "max_output_tokens": config.get("max_output_tokens"),
                "stop_sequences": config.get("stop_sequences")
            }.items() if v is not None}
        )
        # Add safety settings to the config object
        safety_settings = [
            genai_types.SafetySetting(category=getattr(genai_types.HarmCategory, cat, None), threshold=genai_types.HarmBlockThreshold.BLOCK_NONE)
            for cat in ["HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH", "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT"]
        ]
        api_config_obj.safety_settings = [s for s in safety_settings if s.category is not None]

        # Add tools to the config object
        if self.tool_schemas:
            api_config_obj.tools = [genai_types.Tool(function_declarations=self.tool_schemas)]
            logger.info(f"Providing tools: {[t.name for t in self.tool_schemas]}")

        # --- Prepare Contents and System Instruction ---
        try:
            contents_for_api, system_instruction_text = self._prepare_google_contents(messages, instance)
            # Add system instruction to the config object
            if system_instruction_text:
                api_config_obj.system_instruction = system_instruction_text # Correct way for new SDK
        except Exception as e:
            logger.error(f"Error preparing messages/config for Google API: {e}", exc_info=True)
            yield ("error", f"Failed to prepare request data: {e}")
            return
        if not contents_for_api: yield ("error", "No content to send."); return

        # --- API Call using self.client ---
        try:
            logger.info(f"Sending request to {model_name} using client.models.generate_content_stream...")
            # *** Use self.client.models.generate_content_stream ***
            stream = self.client.models.generate_content_stream(
                model=f'models/{model_name}',
                contents=contents_for_api,
                config=api_config_obj, # Use 'config' parameter name
                # stream=True, # REMOVE this redundant argument

            )

            # --- Process Stream ---
            accumulated_text = ""
            accumulated_function_calls = []

            for chunk in stream:
                if stop_event.is_set(): yield ("stopped", accumulated_text); return

                # Simplified Safety checks - check finish reason primarily
                try:
                    if chunk.candidates:
                        finish_reason = getattr(chunk.candidates[0], 'finish_reason', None)
                        if finish_reason and finish_reason.name not in ('STOP', 'MAX_TOKENS', 'UNSPECIFIED'):
                             if finish_reason.name == 'SAFETY':
                                 ratings = getattr(chunk.candidates[0], 'safety_ratings', [])
                                 details = ", ".join([f"{r.category.name}: {r.probability.name}" for r in ratings])
                                 logger.error(f"Content generation stopped for SAFETY. Details: {details}")
                                 yield ("error", f"Content stopped: SAFETY. {details}"); return
                             else: # OTHER, RECITATION, etc.
                                 logger.error(f"Content generation stopped. Reason: {finish_reason.name}")
                                 yield ("error", f"Content stopped: {finish_reason.name}"); return
                except Exception as safety_e: logger.warning(f"Safety check error: {safety_e}")

                # Extract Text
                try:
                    if chunk.text:
                        chunk_text = chunk.text
                        accumulated_text += chunk_text
                        yield ("chunk", chunk_text)
                except (ValueError, AttributeError): pass

                # Extract Function Calls
                if chunk.candidates:
                     try:
                        for part in chunk.candidates[0].content.parts:
                            if part.function_call:
                                fc = part.function_call; args_dict = {}
                                try: # Convert args Map to dict
                                    if hasattr(fc.args, '_pb'): args_dict = json_format.MessageToDict(fc.args._pb)
                                    elif isinstance(fc.args, dict): args_dict = fc.args
                                    else: args_dict = dict(fc.args)
                                except Exception as args_e: logger.error(f"Args conversion error: {args_e}")
                                tool_call_info = {"id": f"gc_{fc.name}_{int(time.time()*1000)}_{len(accumulated_function_calls)}", "name": fc.name, "arguments": args_dict}
                                accumulated_function_calls.append(tool_call_info)
                                logger.info(f"Accumulated tool call: {fc.name}")
                     except Exception as e: logger.warning(f"Error processing chunk parts: {e}")

            # --- End of Stream ---
            logger.info("Stream finished.")
            if accumulated_function_calls:
                yield ("tool_calls", {"calls": accumulated_function_calls, "text": accumulated_text})
            else:
                yield ("finish", accumulated_text)

        except Exception as e:
            logger.error(f"Google API error during generate_content call: {e}", exc_info=True)
            yield ("error", f"Google API error: {str(e)}")
        finally:
            logger.info("GoogleClient send_message_stream_yield finished.")

    # (get_available_models and list_available_models_from_api remain unchanged from your version)

    # --- Model Listing (Using your original, verified functions) ---
    def list_available_models_from_api(self) -> list:
        """Helper to fetch models supporting generate_content from the API."""
        try:
            available_models = []
            logger.info("Attempting to fetch available models from Google API...")
            # Ensure client is initialized
            if not self.client:
                logger.error("Google client not initialized.")
                return self.DEFAULT_MODELS

            fetched_models = self.client.models.list()
            logger.debug(f"Raw models fetched: {fetched_models}") # More verbose debug

            for m in fetched_models:
                # Check if model supports the action needed for text generation
                # Use getattr for safety in case attributes change between versions
                supported_methods = getattr(m, 'supported_generation_methods', [])
                supported_actions = getattr(m, 'supported_actions', []) # Check new SDK attribute name too

                # Check against common names for the generation action
                if "generateContent" in supported_methods or "generateContent" in supported_actions:
                    # Prefer the display_name if available, otherwise use name
                    # Remove the "models/" prefix for a cleaner list
                    model_id = m.name
                    if model_id.startswith('models/'):
                         model_id = model_id.split('/')[-1] # Get cleaner name

                    if model_id not in available_models: # Avoid duplicates
                        available_models.append(model_id)

            if not available_models:
                logger.warning("Could not find any models supporting generateContent via API. Returning defaults.")
                return self.DEFAULT_MODELS

            logger.info(f"Available models fetched from API: {available_models}")
            return available_models
        except Exception as e:
            logger.warning(f"Could not fetch models from API, using defaults: {e}", exc_info=True)
            return self.DEFAULT_MODELS

    def get_available_models(self) -> list:
        """Return a list of model identifiers available for this client."""
        # Call the dynamic listing method
        return self.list_available_models_from_api()
