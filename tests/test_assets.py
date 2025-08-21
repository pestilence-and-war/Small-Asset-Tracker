from it_asset_manager.app.models import User, Asset
from it_asset_manager.app import db

def test_assets_page_unauthenticated(client):
    response = client.get('/assets', follow_redirects=True)
    assert b'Login' in response.data # Should be redirected to login

def test_assets_page_authenticated(client, app):
    with app.app_context():
        user = User(username='testuser', email='test@example.com')
        user.set_password('password')
        db.session.add(user)
        db.session.commit()

    client.post('/login', data={'email': 'test@example.com', 'password': 'password'}, follow_redirects=True)

    response = client.get('/assets')
    assert response.status_code == 200
    assert b'Assets' in response.data

def test_add_asset(client, app):
    with app.app_context():
        admin = User(username='admin', email='admin@example.com', role='admin')
        admin.set_password('password')
        db.session.add(admin)
        db.session.commit()

    client.post('/login', data={'email': 'admin@example.com', 'password': 'password'}, follow_redirects=True)

    response = client.post('/assets/add', data={
        'asset_type': 'PC/Laptop',
        'asset_tag': 'TEST-ASSET-001'
    }, follow_redirects=True)

    assert response.status_code == 200

    with app.app_context():
        asset = Asset.query.filter_by(asset_tag='TEST-ASSET-001').first()
        assert asset is not None
        assert len(asset.history) == 1
        assert asset.history[0].event_type == 'Asset Created'

def test_search_assets(client, app):
    with app.app_context():
        admin = User(username='admin', email='admin@example.com', role='admin')
        admin.set_password('password')
        db.session.add(admin)

        asset1 = Asset(asset_type='PC/Laptop', asset_tag='LAPTOP-001', status='Available')
        asset2 = Asset(asset_type='Mobile Device', asset_tag='MOBILE-001', status='In Use')
        asset3 = Asset(asset_type='PC/Laptop', asset_tag='LAPTOP-002', status='Available')

        db.session.add_all([asset1, asset2, asset3])
        db.session.commit()

    client.post('/login', data={'email': 'admin@example.com', 'password': 'password'}, follow_redirects=True)

    # Search by tag
    response = client.get('/assets?q=LAPTOP')
    assert b'LAPTOP-001' in response.data
    assert b'LAPTOP-002' in response.data
    assert b'MOBILE-001' not in response.data

    # Search by type
    response = client.get('/assets?asset_type=Mobile+Device')
    assert b'MOBILE-001' in response.data
    assert b'LAPTOP-001' not in response.data

    # Search by status
    response = client.get('/assets?status=In+Use')
    assert b'MOBILE-001' in response.data
    assert b'LAPTOP-001' not in response.data

def test_custom_fields(client, app):
    with app.app_context():
        admin = User(username='admin', email='admin@example.com', role='admin')
        admin.set_password('password')
        db.session.add(admin)
        db.session.commit()

    client.post('/login', data={'email': 'admin@example.com', 'password': 'password'}, follow_redirects=True)

    # Create a custom field
    client.post('/settings/custom_fields/add', data={
        'name': 'Warranty Expiry',
        'type': 'date'
    }, follow_redirects=True)

    # Add an asset with a custom field value
    response = client.post('/assets/add', data={
        'asset_type': 'PC/Laptop',
        'asset_tag': 'LAPTOP-003',
        'custom_field_1': '2025-12-31'
    }, follow_redirects=True)
    assert response.status_code == 200

    # View the asset and check for the custom field
    response = client.get('/assets/LAPTOP-003')
    assert b'Warranty Expiry' in response.data
    assert b'2025-12-31' in response.data
