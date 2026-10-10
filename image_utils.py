"""投稿画像を検証し、メタデータを引き継がず保存する。"""
from io import BytesIO
from pathlib import Path
from uuid import uuid4
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.utils import secure_filename

ALLOWED_FORMATS = {'png': 'PNG', 'jpg': 'JPEG', 'jpeg': 'JPEG', 'gif': 'GIF'}


class ImageValidationError(ValueError):
    pass


def save_post_image(upload, directory, max_bytes):
    safe_name = secure_filename(upload.filename or '')
    extension = safe_name.rsplit('.', 1)[-1].lower() if '.' in safe_name else ''
    if extension not in ALLOWED_FORMATS:
        raise ImageValidationError('PNG・JPG・JPEG・GIFの画像を選択してください。')
    data = upload.stream.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ImageValidationError('画像は5MB以下にしてください。')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                if source.format != ALLOWED_FORMATS[extension]:
                    raise ImageValidationError('拡張子と画像の形式が一致しません。')
                source.verify()
            with Image.open(BytesIO(data)) as source:
                # GIFは先頭フレームをPNGとして保存する。
                source.seek(0)
                source.load()
                oriented = ImageOps.exif_transpose(source)
                mode = 'RGB' if extension in {'jpg', 'jpeg'} else 'RGBA'
                pixels = oriented.convert(mode)
                clean = Image.new(mode, pixels.size)
                clean.paste(pixels)
    except (UnidentifiedImageError, OSError, ValueError, EOFError,
            Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        if isinstance(error, ImageValidationError):
            raise
        raise ImageValidationError('画像を読み込めません。別の画像を選択してください。') from error

    suffix = 'jpg' if extension in {'jpg', 'jpeg'} else 'png'
    filename = f'{uuid4().hex}.{suffix}'
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / filename
    # 排他的に作成して既存ファイルを上書きしない。
    with path.open('xb') as output:
        try:
            clean.save(output, format='JPEG' if suffix == 'jpg' else 'PNG')
        except Exception:
            path.unlink(missing_ok=True)
            raise
    return filename
