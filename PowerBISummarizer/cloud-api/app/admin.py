from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import get_current_user, get_password_hash
from app.db import get_db

admin_router = APIRouter(prefix="/admin", tags=["admin"])


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
