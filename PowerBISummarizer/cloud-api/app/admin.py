import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import get_current_user, get_password_hash
from app.config import UPLOAD_DIR
from app.db import get_db

admin_router = APIRouter(prefix="/admin", tags=["admin"])
_INVALID_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")


@admin_router.post(
    "/create-user",
    response_model=schemas.UserOut,
    status_code=status.HTTP_201_CREATED,
)
def create_user(
    payload: schemas.CreateUserRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas admins podem criar usuarios.",
        )

    existing = db.query(models.User).filter(models.User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="E-mail ja cadastrado"
        )

    hashed_pw = get_password_hash(payload.password)

    user = models.User(
        email=payload.email,
        password_hash=hashed_pw,
        is_admin=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return user


def _require_admin(current_user: models.User) -> None:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas admins podem executar esta acao.",
        )


def _sanitize_filename(name: str) -> str:
    sanitized = _INVALID_FILENAME_CHARS.sub("_", name)
    sanitized = sanitized.strip("._") or "layer"
    return sanitized


def _cleanup_file(path: Path) -> None:
    if not path.exists():
        return
    try:
        path.unlink()
    except OSError:
        # Best effort cleanup; ignore failures so API can still return an error
        pass


@admin_router.post(
    "/upload-layer-gpkg",
    response_model=schemas.LayerOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_layer_gpkg(
    file: UploadFile = File(...),
    name: str | None = Form(None),
    epsg: int | None = Form(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _require_admin(current_user)

    filename = file.filename or ""
    if not filename.lower().endswith(".gpkg"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Envie um arquivo com extensao .gpkg",
        )

    base_name = Path(filename).stem
    safe_stem = _sanitize_filename(base_name)
    safe_display_name = name.strip() if name and name.strip() else safe_stem

    now = datetime.utcnow()
    dated_path = Path(str(now.year), f"{now.month:02}", f"{now.day:02}")
    generated_filename = f"{uuid4().hex}_{safe_stem}.gpkg"
    relative_uri = Path("gpkg") / dated_path / generated_filename
    target_dir = UPLOAD_DIR / dated_path
    target_path = target_dir / generated_filename

    target_dir.mkdir(parents=True, exist_ok=True)

    try:
        with target_path.open("wb") as out_file:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                out_file.write(chunk)

        layer = models.Layer(
            name=safe_display_name,
            provider="gpkg",
            uri=str(relative_uri).replace("\\", "/"),
            epsg=epsg,
            srid=epsg,
            schema=None,
            geom_type=None,
            created_by_user_id=current_user.id,
        )
        db.add(layer)
        db.commit()
        db.refresh(layer)
    except IntegrityError as exc:
        db.rollback()
        _cleanup_file(target_path)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ja existe uma camada com este nome.",
        ) from exc
    except HTTPException:
        db.rollback()
        _cleanup_file(target_path)
        raise
    except Exception:
        db.rollback()
        _cleanup_file(target_path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao salvar camada GPKG",
        )
    finally:
        await file.close()

    return layer
