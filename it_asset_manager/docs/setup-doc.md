# Setup Guide

## Prerequisites
- Python 3.8 or higher
- pip (Python package manager)
- Git

## Installation Steps

### 1. Clone the Repository
```bash
git clone https://github.com/yourusername/it_asset_manager.git
cd it_asset_manager
```

### 2. Create Virtual Environment
```bash
# Windows
python -m venv venv
.\venv\Scripts\activate

# Unix/MacOS
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Environment Setup
Create a .env file in the root directory:
```bash
# .env
SECRET_KEY=your-secret-key-here
DATABASE_URL=sqlite:///data/inventory.db
FLASK_ENV=development
```

### 5. Initialize Database
```bash
# Windows
setup.bat

# Unix/MacOS
chmod +x setup.sh
./setup.sh
```

### 6. Run Development Server
```bash
python run.py
```

## Configuration

### Database Configuration
The system uses SQLite by default. To use a different database:

1. Update DATABASE_URL in .env:
```bash
# PostgreSQL example
DATABASE_URL=postgresql://user:password@localhost/dbname

# MySQL example
DATABASE_URL=mysql://user:password@localhost/dbname
```

2. Install required database driver:
```bash
# PostgreSQL
pip install psycopg2-binary

# MySQL
pip install mysqlclient
```

### Development Configuration
Update config.py for development settings:
```python
class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_ECHO = True
```

### Production Configuration
For production deployment:

1. Update config.py:
```python
class ProductionConfig(Config):
    DEBUG = False
    SQLALCHEMY_ECHO = False
```

2. Set environment variables:
```bash
export FLASK_ENV=production
export SECRET_KEY=your-secure-secret-key
```

## Directory Structure
```
it_asset_manager/
├── app/
│   ├── models/
│   ├── routes/
│   ├── static/
│   └── templates/
├── data/
├── docs/
├── config.py
├── requirements.txt
├── run.py
├── setup.bat
└── setup.sh
```

## Testing Setup
```bash
# Install test dependencies
pip install pytest pytest-cov

# Run tests
pytest
```

## Common Issues

### Database Initialization
If database tables aren't created:
```bash
flask db init
flask db migrate
flask db upgrade
```

### Static Files
If static files aren't loading:
1. Check permissions on static directory
2. Verify static path in Flask configuration
3. Clear browser cache

### Virtual Environment
If 'flask' command not found:
1. Ensure virtual environment is activated
2. Reinstall Flask: `pip install -r requirements.txt`

## Next Steps
1. Access application at http://localhost:5000
2. Create initial admin account
3. Configure email settings (if needed)
4. Set up backup strategy

## Updating the Application
```bash
git pull
pip install -r requirements.txt
flask db upgrade
```
