class BaseApiClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.tool_schemas = []

    def add_tool(self, tool_schema: dict):
        self.tool_schemas.append(tool_schema)
