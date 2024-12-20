@echo off
echo Creating Python virtual environment...
python -m venv venv

echo Activating virtual environment...
call venv\Scripts\activate.bat

echo Installing requirements...
pip install -r requirements.txt

echo Creating data directory...
mkdir data 2>nul

echo Initializing database...
python -c "from app import create_app, db; app = create_app(); app.app_context().push(); db.create_all()"

echo Setup complete! Run 'run.bat' to start the application.
pause