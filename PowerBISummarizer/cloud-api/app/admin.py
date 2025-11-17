from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from . import auth, db, models, schemas

admin_router = APIRouter(prefix="/admin", tags=["admin"])


@admin_router.post(
    "/create-user",
    response_model=schemas.CreatedUserResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_user(
    payload: schemas.CreateUserRequest,
    current_user: models.User = Depends(auth.get_current_user),
    db_session: Session = Depends(db.get_db),
):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas admin pode criar usuarios.",
        )

    existing = (
        db_session.query(models.User).filter(models.User.email == payload.email).first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="E-mail ja cadastrado"
        )

    hashed_password = auth.get_password_hash(payload.password)

    user = models.User(
        email=payload.email,
        password_hash=hashed_password,
        is_admin=False,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    return schemas.CreatedUserResponse(
        id=user.id,
        email=user.email,
        is_admin=bool(user.is_admin),
    )
