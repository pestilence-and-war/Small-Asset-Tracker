import sys
from flask import send_from_directory
import os
print(f"Python version: {sys.version}")
from app import create_app

app = create_app()


if __name__ == '__main__':
    app.run(debug=True)