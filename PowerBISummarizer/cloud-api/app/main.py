import os
from typing import List

from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.admin import admin_router
from app.config import UPLOAD_DIR
from . import auth, db, models, schemas

API_BASEPATH = os.getenv("API_BASEPATH", "/api/v1")
ALLOWED_ORIGINS = os.getenv("CORS_ALLOW_ORIGINS", "*")

app = FastAPI(
    title="Power BI Summarizer Cloud API",
    version="1.0.0",
    docs_url=f"{API_BASEPATH}/docs",
    redoc_url=f"{API_BASEPATH}/redoc",
    openapi_url=f"{API_BASEPATH}/openapi.json",
)

origins = [origin.strip() for origin in ALLOWED_ORIGINS.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_router = APIRouter()


@app.on_event("startup")
def _ensure_upload_dir() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@api_router.get("/health", tags=["health"])  # Simple readiness probe
def readiness_check():
    return {"status": "ok"}


@api_router.post("/login", response_model=schemas.TokenResponse)
def login(payload: schemas.LoginRequest, db_session: Session = Depends(db.get_db)):
    user = auth.authenticate_user(db_session, payload.email, payload.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    token = auth.create_access_token(subject=str(user.id))
    return schemas.TokenResponse(access_token=token, expires_in=auth.JWT_EXPIRES)


@api_router.get("/me", response_model=schemas.UserOut)
def get_me(current_user: models.User = Depends(auth.get_current_user)):
    return current_user


@api_router.get("/layers", response_model=List[schemas.LayerOut])
def list_layers(
    current_user: models.User = Depends(auth.get_current_user),
    db_session: Session = Depends(db.get_db),
):
    layers = db_session.query(models.Layer).order_by(models.Layer.name.asc()).all()
    return layers


app.include_router(api_router, prefix=API_BASEPATH)
app.include_router(
    admin_router,
    prefix=API_BASEPATH,
)
