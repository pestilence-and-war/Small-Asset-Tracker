from flask import Flask
from app.units import format_fraction

app = Flask(__name__)

# Register custom Jinja filter
app.jinja_env.filters['format_fraction'] = format_fraction

from app import routes
