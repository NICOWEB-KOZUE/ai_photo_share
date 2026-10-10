from pathlib import Path
import os
import time
from datetime import timedelta, timezone

import click
from flask import Flask, render_template, redirect, url_for, flash, session, request, send_from_directory, abort
from cachelib import FileSystemCache
from dotenv import load_dotenv
from flask_login import LoginManager, current_user, login_user, logout_user, login_required
from flask_session import Session
from flask_wtf.csrf import CSRFProtect, CSRFError
from peewee import IntegrityError
from forms import RegisterForm, LoginForm, LogoutForm, PostForm
from image_utils import save_post_image, ImageValidationError

from models import Post, User, db


def initialize_database(database_path):
    """既存データを残して、保存先と必要なテーブルを用意する。"""
    Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    with db.connection_context():
        db.create_tables([User, Post], safe=True)


def create_app(test_config=None):
    root = Path(__file__).resolve().parent
    load_dotenv(root / ".env")
    app = Flask(__name__)
    app.config.from_mapping(
        DATABASE=Path(__file__).resolve().parent / "instance" / "app.sqlite3",
        UPLOAD_FOLDER=root / "uploads" / "posts",
        MAX_IMAGE_BYTES=5 * 1024 * 1024,
        MAX_CONTENT_LENGTH=6 * 1024 * 1024,
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
    upload_folder = Path(app.config["UPLOAD_FOLDER"])
    if not upload_folder.is_absolute():
        upload_folder = root / upload_folder
    app.config["UPLOAD_FOLDER"] = upload_folder
    upload_folder.mkdir(parents=True, exist_ok=True)
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
        elif request.endpoint in {"post_index", "register", "login", "post_create"} and request.method == "GET":
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
        # エラーページでも巨大なPOST本文を再解析しない。
        return {"logout_form": LogoutForm(formdata=None)}

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        return render_template("errors/error.html", message="フォームの有効期限が切れたか、送信内容が不正です。画面を開き直してください。"), 400

    @app.errorhandler(413)
    def upload_too_large(error):
        return render_template("errors/error.html", message="送信容量が大きすぎます。5MB以下の画像を選び直してください。", retry_upload=True), 413

    @app.template_filter("japan_time")
    def japan_time(value):
        return value.replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=9))).strftime("%Y.%m.%d %H:%M")

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
        posts = list(Post.select(Post, User).join(User).order_by(Post.created_at.desc(), Post.id.desc()))
        return render_template("posts/index.html", posts=posts)

    @app.route("/posts/new", methods=["GET", "POST"])
    @login_required
    def post_create():
        form = PostForm()
        if form.validate_on_submit():
            try:
                filename = save_post_image(form.photo.data, app.config["UPLOAD_FOLDER"], app.config["MAX_IMAGE_BYTES"])
            except ImageValidationError as error:
                form.photo.errors.append(str(error))
            except OSError:
                app.logger.exception("画像の保存に失敗しました。")
                return render_template("errors/error.html", message="画像を保存できませんでした。時間をおいて再度お試しください。", retry_upload=True), 500
            else:
                try:
                    with db.atomic():
                        Post.create(user=current_user.id, image_filename=filename, caption=form.caption.data or '')
                except Exception:
                    app.logger.exception("投稿の保存に失敗しました。")
                    try:
                        (app.config["UPLOAD_FOLDER"] / filename).unlink(missing_ok=True)
                    except OSError:
                        app.logger.exception("未保存投稿の画像を削除できませんでした: %s", filename)
                    return render_template("errors/error.html", message="投稿を保存できませんでした。時間をおいて再度お試しください。", retry_upload=True), 500
                flash("写真を投稿しました。")
                return redirect(url_for("post_index"))
        return render_template("posts/new.html", form=form)

    @app.get("/uploads/posts/<filename>")
    def uploaded_file(filename):
        if filename.startswith('.') or not Post.get_or_none(Post.image_filename == filename):
            abort(404)
        response = send_from_directory(app.config["UPLOAD_FOLDER"], filename)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

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
