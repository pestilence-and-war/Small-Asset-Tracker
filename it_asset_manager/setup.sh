#!/bin/bash
echo "Creating Python virtual environment..."
python3 -m venv venv

echo "Activating virtual environment..."
source venv/bin/activate

echo "Installing requirements..."
pip install -r requirements.txt

echo "Creating data directory..."
mkdir -p data

echo "Initializing database..."
python3 -c "from app import create_app, db; app = create_app(); app.app_context().push(); db.create_all()"

echo "Setup complete! Run './run.sh' to start the application."
