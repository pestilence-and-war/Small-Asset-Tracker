# Developer Guide

## Development Environment Setup

### Required Tools
- Visual Studio Code or PyCharm
- Git
- Python 3.8+
- SQLite Browser (optional)

### IDE Configuration
#### VS Code Extensions
- Python
- SQLite
- Tailwind CSS IntelliSense
- Python Test Explorer

### Code Style
Follow PEP 8 with these additions:
```python
# Maximum line length
max-line-length = 100

# Import ordering
from flask import ...
from third_party import ...
from app import ...
from . import ...
```

## Project Structure

### Blueprint Organization
```python
# app/routes/__init__.py
from flask import Blueprint

blueprint = Blueprint('name', __name__, url_prefix='/prefix')

from . import routes  # Import routes after blueprint creation
```

### Model Definition
```python
# app/models/base.py
from app import db

class BaseModel(db.Model):
    __abstract__ = True
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    updated_at = db.Column(db.DateTime, default=db.func.current_timestamp(),
                          onupdate=db.func.current_timestamp())
```

## Development Workflow

### 1. Feature Development
```bash
# Create feature branch
git checkout -b feature/name

# Make changes
# Test changes
# Commit changes

# Push to remote
git push origin feature/name
```

### 2. Database Changes
```python
# Create migration
flask db migrate -m "Description"

# Review migration file
# Apply migration
flask db upgrade

# Rollback if needed
flask db downgrade
```

### 3. Testing
```python
# app/tests/test_asset.py
def test_asset_creation(client):
    response = client.post('/assets/add', data={
        'asset_type': 'PC/Laptop',
        'asset_tag': 'TEST001'
    })
    assert response.status_code == 200
```

## Frontend Development

### HTMX Pattern
```html
<!-- Button trigger -->
<button hx-get="/path"
        hx-target="#element"
        hx-swap="outerHTML">
    Action
</button>

<!-- Target element -->
<div id="element">
    Content to be replaced
</div>
```

### Tailwind Classes
Follow utility-first approach:
```html
<div class="flex items-center justify-between p-4 bg-white shadow rounded-lg">
    <h2 class="text-xl font-semibold text-gray-800">Title</h2>
    <!-- Additional content -->
</div>
```

## Error Handling

### Route Level
```python
@bp.errorhandler(404)
def not_found_error(error):
    return render_template('errors/404.html'), 404

@bp.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('errors/500.html'), 500
```

### Form Validation
```python
from flask_wtf import FlaskForm
from wtforms import StringField, ValidationError

class AssetForm(FlaskForm):
    asset_tag = StringField('Asset Tag', validators=[
        DataRequired(),
        Regexp(r'^[A-Za-z0-9-]+$', message="Invalid characters in asset tag")
    ])
```

## Debug Techniques

### Database Debugging
```python
# Enable SQL logging
app.config['SQLALCHEMY_ECHO'] = True

# Query inspection
query = Asset.query.filter_by(status='Available')
print(query.statement.compile(compile_kwargs={"literal_binds": True}))
```

### HTMX Debugging
```javascript
htmx.logAll();  // Enable HTMX logging

document.body.addEventListener('htmx:afterRequest', function(evt) {
    console.log('HTMX Request Complete:', evt.detail);
});
```

## Performance Optimization

### Query Optimization
```python
# Eager loading
assets = Asset.query.options(
    joinedload(Asset.assignments).joinedload(Assignment.employee)
).all()

# Pagination
ITEMS_PER_PAGE = 25
page = request.args.get('page', 1, type=int)
pagination = Asset.query.paginate(page=page, per_page=ITEMS_PER_PAGE)
```

### Caching
```python
from flask_caching import Cache

cache = Cache()

@cache.memoize(timeout=300)
def get_asset_stats():
    return Asset.query.with_entities(
        func.count(Asset.id),
        func.count(case([(Asset.status == 'Available', 1)]))
    ).first()
```

## Security Best Practices

### Input Validation
```python
def sanitize_input(text):
    return bleach.clean(text, tags=[], strip=True)

@bp.route('/asset/<asset_tag>')
def view_asset(asset_tag):
    asset_tag = sanitize_input(asset_tag)
    asset = Asset.query.filter_by(asset_tag=asset_tag).first_or_404()
    return render_template('asset_details.html', asset=asset)
```

### CSRF Protection
```html
<form method="post">
    {{ form.csrf_token }}
    <!-- Form fields -->
</form>
```

## Deployment Checklist

1. Security
   - [ ] Debug mode disabled
   - [ ] Secret key configured
   - [ ] CSRF protection enabled
   - [ ] SQL logging disabled

2. Performance
   - [ ] Database indexes created
   - [ ] Static files compressed
   - [ ] Caching configured

3. Monitoring
   - [ ] Logging configured
   - [ ] Error tracking set up
   - [ ] Performance monitoring enabled

## Contributing Guidelines

1. Code Style
   - Follow PEP 8
   - Use type hints
   - Document functions and classes

2. Pull Requests
   - Include tests
   - Update documentation
   - Add migration scripts if needed

3. Commit Messages
   - Use present tense
   - Be descriptive
   - Reference issues
