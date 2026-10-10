from io import BytesIO
import re
from unittest.mock import patch

import pytest
from PIL import Image
from peewee import IntegrityError

from app import create_app, initialize_database
from models import User, Post, db


@pytest.fixture
def app(tmp_path):
    app = create_app({'TESTING': True, 'SECRET_KEY': 'test-only',
        'DATABASE': tmp_path / 'db.sqlite3', 'UPLOAD_FOLDER': tmp_path / 'uploads' / 'posts',
        'SESSION_FILE_DIR': tmp_path / 'sessions', 'SESSION_COOKIE_SECURE': False})
    initialize_database(app.config['DATABASE'])
    with db.connection_context():
        user = User(username='PhotoUser', email='photo@example.com')
        user.set_password('abcd')
        user.save()
    yield app
    if not db.is_closed():
        db.close()


def token(client, route='/login'):
    return re.search(r'name="csrf_token"[^>]*value="([^"]+)"', client.get(route).text).group(1)


@pytest.fixture
def client(app):
    client = app.test_client()
    client.post('/login', data={'email': 'photo@example.com', 'password': 'abcd', 'csrf_token': token(client)})
    return client


def picture(format='PNG'):
    output = BytesIO()
    image = Image.new('RGB', (20, 30), 'blue')
    exif = Image.Exif()
    exif[270] = 'private metadata'
    image.save(output, format=format, **({'exif': exif} if format in ('PNG', 'JPEG') else {}))
    output.seek(0)
    return output


def submit(client, image=None, filename='image.png', caption='Hello'):
    return client.post('/posts/new', data={'csrf_token': token(client, '/posts/new'),
        'photo': (image if image is not None else picture(), filename), 'caption': caption})


@pytest.mark.parametrize('format,extension', [('PNG','png'), ('JPEG','jpg'), ('JPEG','jpeg'), ('GIF','gif')])
def test_upload_and_public_display(app, client, format, extension):
    assert submit(client, picture(format), f'../../sample.{extension}', '<script>alert(1)</script>').status_code == 302
    with db.connection_context():
        post = Post.get()
        name = post.image_filename
        assert post.user.username == 'PhotoUser'
    assert '/' not in name and '..' not in name
    public = app.test_client()
    result = public.get('/')
    assert 'PhotoUser' in result.text and '&lt;script&gt;' in result.text
    assert '<script>alert(1)</script>' not in result.text
    response = public.get('/uploads/posts/' + name)
    assert response.status_code == 200
    with Image.open(BytesIO(response.data)) as saved:
        assert not saved.getexif()
        assert getattr(saved, 'n_frames', 1) == 1


@pytest.mark.parametrize('data,name', [(b'not image','fake.png'), (b'x','file.svg')])
def test_invalid_images(app, client, data, name):
    assert submit(client, BytesIO(data), name).status_code == 200
    assert list(app.config['UPLOAD_FOLDER'].iterdir()) == []
    with db.connection_context():
        assert Post.select().count() == 0


def test_mismatched_format(app, client):
    assert '一致しません' in submit(client, picture('PNG'), 'fake.jpg').text


@pytest.mark.parametrize('length,valid', [(0, True), (140, True), (141, False)])
def test_caption(app, client, length, valid):
    assert (submit(client, caption='あ' * length).status_code == 302) == valid


def test_upload_limits(app, client):
    result = submit(client, BytesIO(b'x' * (5*1024*1024+1)))
    assert result.status_code == 200 and '5MB以下' in result.text
    assert submit(client, BytesIO(b'x' * (6*1024*1024+1))).status_code == 413
    assert list(app.config['UPLOAD_FOLDER'].iterdir()) == []


def test_auth_csrf_and_missing_photo(app, client):
    anonymous = app.test_client()
    assert anonymous.get('/posts/new').status_code == 302
    assert anonymous.post('/posts/new', data={'csrf_token': token(anonymous), 'photo': (picture(),'a.png')}).status_code == 302
    assert client.post('/posts/new', data={'photo': (picture(),'a.png')}).status_code == 400
    assert client.post('/posts/new', data={'csrf_token': token(client, '/posts/new')}).status_code == 200
    assert list(app.config['UPLOAD_FOLDER'].iterdir()) == []


def test_db_failure_cleanup(app, client):
    with patch.object(Post, 'create', side_effect=IntegrityError('test failure')):
        assert submit(client).status_code == 500
    assert list(app.config['UPLOAD_FOLDER'].iterdir()) == []


def test_file_routes(app, client):
    (app.config['UPLOAD_FOLDER'] / 'unlinked.png').write_bytes(b'not public')
    for name in ['unlinked.png', '.gitkeep', '..%2F..%2F.env', 'missing.png']:
        assert client.get('/uploads/posts/' + name).status_code == 404


def test_repeated_names_do_not_overwrite(app, client):
    assert submit(client).status_code == 302
    assert submit(client).status_code == 302
    assert len(list(app.config['UPLOAD_FOLDER'].iterdir())) == 2
