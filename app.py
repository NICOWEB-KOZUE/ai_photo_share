from pathlib import Path

import click
from flask import Flask, render_template

from models import Post, User, db


def initialize_database(database_path):
    """既存データを残して、保存先と必要なテーブルを用意する。"""
    Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    with db.connection_context():
        db.create_tables([User, Post], safe=True)


def create_app(test_config=None):
    app = Flask(__name__, static_folder=None)
    app.config.from_mapping(
        DATABASE=Path(__file__).resolve().parent / "instance" / "app.sqlite3",
    )
    if test_config:
        app.config.update(test_config)

    db.init(str(app.config["DATABASE"]))

    @app.before_request
    def open_database():
        db.connect(reuse_if_open=True)

    @app.teardown_request
    def close_database(error):
        if not db.is_closed():
            db.close()

    @app.cli.command("init-db")
    def init_database():
        """既存データを残して、必要なテーブルを作成する。"""
        initialize_database(app.config["DATABASE"])
        click.echo("データベースを初期化しました。")

    @app.get("/")
    def post_index():
        return render_template("posts/index.html")

    return app


if __name__ == "__main__":
    app = create_app()
    initialize_database(app.config["DATABASE"])
    app.run(port=8000)
