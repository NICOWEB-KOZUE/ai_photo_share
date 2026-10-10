from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired, FileAllowed
from wtforms import TextAreaField
from wtforms.validators import Optional
from wtforms import PasswordField, StringField, SubmitField
from wtforms.validators import Email, InputRequired, Length


def strip_text(value):
    return value.strip() if value else value


def normalize_email(value):
    return value.strip().lower() if value else value


class RegisterForm(FlaskForm):
    username = StringField('ユーザー名', filters=[strip_text], validators=[
        InputRequired(), Length(min=1, max=50, message='ユーザー名は1〜50文字で入力してください。')])
    email = StringField('メールアドレス', filters=[normalize_email], validators=[
        InputRequired(), Length(max=254), Email(message='メールアドレスの形式を確認してください。')])
    password = PasswordField('パスワード', validators=[
        InputRequired(), Length(min=4, max=4, message='パスワードはちょうど4文字で入力してください。')])
    submit = SubmitField('登録する')


class LoginForm(FlaskForm):
    # 登録時だけ4文字に制限し、変更前のパスワードでもログインできるようにする。
    email = StringField('メールアドレス', filters=[normalize_email], validators=[
        InputRequired(), Length(max=254), Email(message='メールアドレスの形式を確認してください。')])
    password = PasswordField('パスワード', validators=[InputRequired(), Length(max=128)])
    submit = SubmitField('ログイン')


class LogoutForm(FlaskForm):
    submit = SubmitField('ログアウト')


class PostForm(FlaskForm):
    photo = FileField('写真', validators=[
        FileRequired('写真を1枚選択してください。'),
        FileAllowed(['png', 'jpg', 'jpeg', 'gif'], 'PNG・JPG・JPEG・GIFのみ投稿できます。')])
    caption = TextAreaField('キャプション（任意）', validators=[
        Optional(strip_whitespace=False), Length(max=140, message='キャプションは140文字以内で入力してください。')])
    submit = SubmitField('投稿する')
