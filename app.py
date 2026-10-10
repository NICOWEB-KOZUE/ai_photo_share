from pathlib import Path
import os
import time
from datetime import timedelta

import click
from flask import Flask, render_template, redirect, url_for, flash, session, request
from cachelib import FileSystemCache
from dotenv import load_dotenv
from flask_login import LoginManager, current_user, login_user, logout_user, login_required
from flask_session import Session
from flask_wtf.csrf import CSRFProtect, CSRFError
from peewee import IntegrityError
from forms import RegisterForm, LoginForm, LogoutForm

from models import Post, User, db


def initialize_database(database_path):
    """既存データを残して、保存先と必要なテーブルを用意する。"""
    Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    with db.connection_context():
        db.create_tables([User, Post], safe=True)


def create_app(test_config=None):
    root = Path(__file__).resolve().parent
    load_dotenv(root / ".env")
    app = Flask(__name__, static_folder=None)
    app.config.from_mapping(
        DATABASE=Path(__file__).resolve().parent / "instance" / "app.sqlite3",
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        SESSION_TYPE="cachelib",
        SESSION_FILE_DIR=root / "instance" / "sessions",
        SESSION_PERMANENT=True,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=24),
        SESSION_REFRESH_EACH_REQUEST=False,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true",
    )
    if test_config:
        app.config.update(test_config)
    if not app.config["SECRET_KEY"]:
        raise RuntimeError("SECRET_KEYを環境変数または.envに設定してください。")
    app.config["SESSION_CACHELIB"] = FileSystemCache(
        cache_dir=str(app.config["SESSION_FILE_DIR"]), threshold=0)
    Session(app)
    login_manager = LoginManager(app)
    login_manager.login_view = "login"
    login_manager.login_message = "ログインしてください。"

    db.init(str(app.config["DATABASE"]))

    @app.before_request
    def open_database():
        db.connect(reuse_if_open=True)

    @app.before_request
    def check_session_expiry():
        if "_user_id" not in session:
            return
        now = time.time()
        last_active = session.get("last_active", 0)
        if now - last_active >= app.permanent_session_lifetime.total_seconds():
            logout_user()
            session.clear()
        elif request.endpoint in {"post_index", "register", "login"} and request.method == "GET":
            session["last_active"] = now

    # 期限切れを先に処理し、古いセッションのPOSTも拒否する。
    CSRFProtect(app)

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return User.get_or_none(User.id == int(user_id))
        except (TypeError, ValueError):
            return None

    @app.context_processor
    def auth_forms():
        return {"logout_form": LogoutForm()}

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        return render_template("errors/error.html", message="フォームの有効期限が切れたか、送信内容が不正です。画面を開き直してください。"), 400

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

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if current_user.is_authenticated:
            return redirect(url_for("post_index"))
        form = RegisterForm()
        if form.validate_on_submit():
            if User.get_or_none(User.username == form.username.data):
                form.username.errors.append("このユーザー名は既に使用されています。")
            if User.get_or_none(User.email == form.email.data):
                form.email.errors.append("このメールアドレスは既に登録されています。")
            if not form.errors:
                user = User(username=form.username.data, email=form.email.data)
                user.set_password(form.password.data)
                try:
                    with db.atomic():
                        user.save()
                except IntegrityError:
                    form.username.errors.append("ユーザー名またはメールアドレスは既に登録されています。")
                else:
                    flash("登録が完了しました。ログインしてください。")
                    return redirect(url_for("login"))
        return render_template("auth/register.html", form=form)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("post_index"))
        form = LoginForm()
        if form.validate_on_submit():
            user = User.get_or_none(User.email == form.email.data)
            if user and user.check_password(form.password.data):
                # 古いCSRF情報を捨て、認証成功後にセッションIDを更新する。
                session.clear()
                login_user(user, remember=False)
                session.permanent = True
                session["last_active"] = time.time()
                app.session_interface.regenerate(session)
                return redirect(url_for("post_index"))
            form.password.errors.append("メールアドレスまたはパスワードを確認してください。")
        return render_template("auth/login.html", form=form)

    @app.post("/logout")
    @login_required
    def logout():
        logout_user()
        session.clear()
        return redirect(url_for("post_index"))

    return app


if __name__ == "__main__":
    app = create_app()
    initialize_database(app.config["DATABASE"])
    app.run(port=8000)
