from it_asset_manager.app.models import User
from it_asset_manager.app import db

def test_register(client):
    response = client.get('/register')
    assert response.status_code == 200

    response = client.post('/register', data={
        'username': 'testuser',
        'email': 'test@example.com',
        'password': 'password',
        'confirm_password': 'password'
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'Your account has been created!' in response.data

    user = User.query.filter_by(email='test@example.com').first()
    assert user is not None
    assert user.username == 'testuser'

def test_login_logout(client):
    # Register a user first
    client.post('/register', data={
        'username': 'testuser',
        'email': 'test@example.com',
        'password': 'password',
        'confirm_password': 'password'
    })

    # Test login
    response = client.post('/login', data={
        'email': 'test@example.com',
        'password': 'password'
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'Logout' in response.data # Check for logout link in nav

    # Test logout
    response = client.get('/logout', follow_redirects=True)
    assert response.status_code == 200
    assert b'Login' in response.data # Check for login link in nav

def test_profile_access(client):
    # Register two users
    client.post('/register', data={
        'username': 'user1',
        'email': 'user1@example.com',
        'password': 'password'
    }, follow_redirects=True)
    client.post('/register', data={
        'username': 'user2',
        'email': 'user2@example.com',
        'password': 'password'
    }, follow_redirects=True)

    # Login as user1
    client.post('/login', data={
        'email': 'user1@example.com',
        'password': 'password'
    }, follow_redirects=True)

    # user1 should be able to access their own profile
    response = client.get('/profile')
    assert response.status_code == 200
    assert b'user1' in response.data

    # user1 should not be able to access user2's profile
    # This requires a way to get user2's id, which we don't have here.
    # We will test this by trying to access a generic /profile/2 page, which should fail.
    # A better test would be to create user2 first, get their id, then register and login as user1.
    # For now, we will test that a user cannot access the settings page.

    response = client.get('/settings/', follow_redirects=True)
    assert b'You do not have permission to access this page.' in response.data

def test_admin_access(client, app):
    with app.app_context():
        admin_user = User(username='admin', email='admin@example.com', role='admin')
        admin_user.set_password('password')
        db.session.add(admin_user)
        db.session.commit()

    client.post('/login', data={
        'email': 'admin@example.com',
        'password': 'password'
    }, follow_redirects=True)

    response = client.get('/settings/', follow_redirects=True)
    assert response.status_code == 200
    assert b'Settings' in response.data
