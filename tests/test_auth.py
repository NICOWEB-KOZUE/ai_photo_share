import re
import time

import pytest
from werkzeug.security import check_password_hash

from app import create_app, initialize_database
from models import User, db

PASSWORD = 'Ab1!'


@pytest.fixture
def app(tmp_path):
    application = create_app({
        'TESTING': True,
        'SECRET_KEY': 'test-only-secret',
        'DATABASE': tmp_path / 'test.sqlite3',
        'SESSION_FILE_DIR': tmp_path / 'sessions',
        'SESSION_COOKIE_SECURE': False,
    })
    initialize_database(application.config['DATABASE'])
    yield application
    if not db.is_closed():
        db.close()


@pytest.fixture
def client(app):
    return app.test_client()


def csrf(client, url):
    response = client.get(url)
    return re.search(r'name="csrf_token"[^>]*value="([^"]+)"', response.text).group(1)


def register(client, username='Alice', email='alice@example.com', password=PASSWORD):
    return client.post('/register', data={
        'csrf_token': csrf(client, '/register'),
        'username': username, 'email': email, 'password': password,
    })


def login(client, email='alice@example.com', password=PASSWORD, url='/login'):
    return client.post(url, data={
        'csrf_token': csrf(client, '/login'), 'email': email, 'password': password,
    })


def test_auth_flow(client, app):
    assert client.get('/').status_code == 200
    assert '写真共有アプリ' in client.get('/').text
    assert register(client, email=' Alice@Example.com ').location == '/login'
    with db.connection_context():
        user = User.get()
        assert user.email == 'alice@example.com'
        assert user.password_hash != PASSWORD
        assert check_password_hash(user.password_hash, PASSWORD)
    token = csrf(client, '/login')
    old_cookie = client.get_cookie('session').value
    response = client.post('/login?next=https://example.org', data={
        'csrf_token': token, 'email': ' ALICE@example.com ', 'password': PASSWORD})
    assert response.location == '/'
    assert client.get_cookie('session').value != old_cookie
    assert 'Alice さん' in client.get('/').text
    assert client.get('/login').location == '/'
    assert client.get('/register').location == '/'
    old_authenticated_cookie = client.get_cookie('session').value
    response = client.post('/logout', data={'csrf_token': csrf(client, '/')})
    assert response.location == '/'
    assert client.get_cookie('session') is None
    client.set_cookie('session', old_authenticated_cookie)
    assert 'Alice さん' not in client.get('/').text
    assert db.is_closed()


def test_duplicates_and_case(client):
    register(client)
    assert '既に使用' in register(client, ' Alice ', 'other@example.com').text
    assert '既に登録' in register(client, 'Bob', ' ALICE@EXAMPLE.COM ').text
    assert register(client, 'alice', 'other@example.com').status_code == 302
    with db.connection_context():
        assert User.select().count() == 2


@pytest.mark.parametrize('password,valid', [('a'*3, False), ('a'*4, True), ('a'*5, False), ('a'*128, False)])
def test_password_limits(client, password, valid):
    result = register(client, password=password)
    assert (result.status_code == 302) is valid
    if valid:
        assert login(client, password=password).location == '/'
    else:
        assert 'value="' + password + '"' not in result.text


@pytest.mark.parametrize('name,email', [('   ', 'a@example.com'), ('x'*51, 'a@example.com'), ('Alice', 'invalid')])
def test_invalid_registration(client, name, email):
    assert register(client, name, email).status_code == 200
    with db.connection_context():
        assert User.select().count() == 0


def test_wrong_password(client):
    register(client)
    response = login(client, password='wrong-password-123')
    assert response.status_code == 200
    assert 'メールアドレスまたはパスワードを確認' in response.text
    assert 'wrong-password-123' not in response.text
    assert 'Alice さん' not in client.get('/').text


@pytest.mark.parametrize('url', ['/register', '/login', '/logout'])
def test_csrf_required(client, url):
    assert client.post(url).status_code == 400


def test_logout_methods(client):
    assert client.get('/logout').status_code == 405
    assert client.post('/logout', data={'csrf_token': csrf(client, '/login')}).status_code == 302


def test_expiry_and_refresh(client):
    register(client)
    login(client)
    with client.session_transaction() as session:
        session['last_active'] = time.time() - 3600
        old = session['last_active']
    assert 'Alice さん' in client.get('/').text
    with client.session_transaction() as session:
        assert session['last_active'] > old
        session['last_active'] = time.time() - 86401
    assert 'Alice さん' not in client.get('/').text
    with client.session_transaction() as session:
        assert '_user_id' not in session


def test_deleted_user(client):
    register(client)
    login(client)
    with db.connection_context():
        User.delete().execute()
    assert client.get('/').status_code == 200
    assert 'Alice さん' not in client.get('/').text


def test_missing_secret():
    with pytest.raises(RuntimeError, match='SECRET_KEY'):
        create_app({'SECRET_KEY': None})


def test_existing_long_password_login(client):
    # 条件変更前のアカウントも、保存済みのパスワードでログインできる。
    with db.connection_context():
        user = User(username='Alice', email='alice@example.com')
        user.set_password('existing-long-password')
        user.save()
    assert login(client, password='existing-long-password').location == '/'
