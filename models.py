from datetime import datetime, timezone
from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from peewee import (
    AutoField,
    CharField,
    Check,
    DateTimeField,
    ForeignKeyField,
    Model,
    SqliteDatabase,
    TextField,
)


db = SqliteDatabase(None, pragmas={"foreign_keys": 1})


def utc_now():
    # DBではUTCに統一し、タイムゾーン情報なしの日時として保存する。
    return datetime.now(timezone.utc).replace(tzinfo=None)


class BaseModel(Model):
    class Meta:
        database = db


class User(UserMixin, BaseModel):
    id = AutoField()
    username = CharField(max_length=50, unique=True, collation="BINARY")
    email = CharField(max_length=254, unique=True)
    password_hash = TextField()

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    class Meta:
        table_name = "users"


class Post(BaseModel):
    id = AutoField()
    user = ForeignKeyField(User, backref="posts", on_delete="RESTRICT")
    image_filename = CharField(max_length=255, unique=True)
    caption = CharField(
        max_length=140, default="", constraints=[Check("length(caption) <= 140")]
    )
    created_at = DateTimeField(default=utc_now)

    class Meta:
        table_name = "posts"
