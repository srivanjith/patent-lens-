import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, Any
from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import (
    hash_password, verify_password, create_access_token, create_refresh_token,
    get_current_user, decode_token
)
from app.core.config import settings
from app.models.models import User, UserDoc
from app.schemas.schemas import (
    UserRegisterRequest, UserLoginRequest, GoogleAuthRequest, TokenResponse, UserOut,
    OTPVerifyRequest, OTPResendRequest
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


def generate_otp_code() -> str:
    """Generate a 6-digit numeric OTP code."""
    return f"{random.randint(100000, 999999)}"


def _get_dt(val: Any) -> datetime:
    """Extract a concrete datetime object for Pyright type safety."""
    if isinstance(val, datetime):
        return val
    return datetime.now(timezone.utc)


def _get_str(val: Any, default: str = "") -> str:
    """Extract a concrete string object for Pyright type safety."""
    if isinstance(val, str):
        return val
    return default


def _get_bool(val: Any, default: bool = False) -> bool:
    """Extract a concrete boolean value for Pyright type safety."""
    if isinstance(val, bool):
        return val
    return default


async def _get_user_by_email(email: str, db: Session) -> Tuple[Optional[UserDoc], Optional[User]]:
    email_clean = email.lower().strip()
    user_doc: Optional[UserDoc] = None
    try:
        user_doc = await UserDoc.find_one(UserDoc.email == email_clean)
    except Exception:
        pass

    user_sql: Optional[User] = None
    if db:
        try:
            user_sql = db.query(User).filter(User.email == email_clean).first()
        except Exception:
            pass

    return user_doc, user_sql


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register_user(request: UserRegisterRequest, response: Response, db: Session = Depends(get_db)):
    """Register a new user account and initiate first-time OTP verification."""
    email_clean = request.email.lower().strip()
    user_doc, existing = await _get_user_by_email(email_clean, db)

    user_out: Optional[UserOut] = None

    if user_doc is not None or existing is not None:
        is_verified = bool(
            (user_doc and user_doc.is_verified) or (existing and _get_bool(existing.is_verified))
        )
        if is_verified:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An account with this email address already exists and is verified."
            )
        # Update unverified user with new password and fresh OTP
        new_pwd_hash = hash_password(request.password)
        otp = generate_otp_code()
        exp = datetime.now(timezone.utc) + timedelta(minutes=10)

        if user_doc is not None:
            user_doc.name = request.name.strip()
            user_doc.password_hash = new_pwd_hash
            user_doc.otp_code = otp
            user_doc.otp_expires_at = exp
            await user_doc.save()

        if existing is not None:
            setattr(existing, "name", request.name.strip())
            setattr(existing, "password_hash", new_pwd_hash)
            setattr(existing, "otp_code", otp)
            setattr(existing, "otp_expires_at", exp)
            db.commit()
            db.refresh(existing)
            user_out = UserOut(
                id=_get_str(existing.id),
                name=_get_str(existing.name),
                email=_get_str(existing.email),
                is_verified=_get_bool(existing.is_verified),
                created_at=_get_dt(existing.created_at)
            )
        elif user_doc is not None:
            user_out = UserOut(
                id=_get_str(user_doc.id),
                name=_get_str(user_doc.name),
                email=_get_str(user_doc.email),
                is_verified=_get_bool(user_doc.is_verified),
                created_at=_get_dt(user_doc.created_at)
            )

        return TokenResponse(
            require_otp=True,
            otp_sent_to=email_clean,
            demo_otp=otp,
            user=user_out
        )

    otp = generate_otp_code()
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)

    user_id = str(uuid.uuid4())
    pwd_hash = hash_password(request.password)

    # Save to MongoDB Atlas
    new_user_doc: Optional[UserDoc] = None
    try:
        new_user_doc = UserDoc(
            id=user_id,
            name=request.name.strip(),
            email=email_clean,
            password_hash=pwd_hash,
            is_verified=False,
            otp_code=otp,
            otp_expires_at=expires
        )
        await new_user_doc.insert()
    except Exception:
        new_user_doc = None

    # Dual persistence in SQL DB
    try:
        user = User(
            id=user_id,
            name=request.name.strip(),
            email=email_clean,
            password_hash=pwd_hash,
            is_verified=False,
            otp_code=otp,
            otp_expires_at=expires
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        user_out = UserOut(
            id=_get_str(user.id),
            name=_get_str(user.name),
            email=_get_str(user.email),
            is_verified=_get_bool(user.is_verified),
            created_at=_get_dt(user.created_at)
        )
    except Exception:
        if new_user_doc is not None:
            user_out = UserOut(
                id=_get_str(new_user_doc.id),
                name=_get_str(new_user_doc.name),
                email=_get_str(new_user_doc.email),
                is_verified=_get_bool(new_user_doc.is_verified),
                created_at=_get_dt(new_user_doc.created_at)
            )
        else:
            raise

    return TokenResponse(
        require_otp=True,
        otp_sent_to=email_clean,
        demo_otp=otp,
        user=user_out
    )


@router.post("/login", response_model=TokenResponse)
async def login_user(request: UserLoginRequest, response: Response, db: Session = Depends(get_db)):
    """Authenticate user credentials and issue JWT tokens (or request OTP if unverified)."""
    email_clean = request.email.lower().strip()
    user_doc, user_sql = await _get_user_by_email(email_clean, db)

    if not user_doc and not user_sql:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No account found with this email address. Please sign up to create an account.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    user_obj = user_doc if user_doc is not None else user_sql
    assert user_obj is not None

    pwd_hash = _get_str(user_obj.password_hash)
    if not verify_password(request.password, pwd_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password. Please check your password and try again.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    is_verified = _get_bool(user_obj.is_verified)
    user_id = _get_str(user_obj.id)
    user_name = _get_str(user_obj.name)
    created_at = _get_dt(user_obj.created_at)

    # Check if first-time verification is required
    if not is_verified:
        otp = generate_otp_code()
        exp = datetime.now(timezone.utc) + timedelta(minutes=10)
        if user_doc is not None:
            user_doc.otp_code = otp
            user_doc.otp_expires_at = exp
            await user_doc.save()
        if user_sql is not None:
            setattr(user_sql, "otp_code", otp)
            setattr(user_sql, "otp_expires_at", exp)
            db.commit()

        return TokenResponse(
            require_otp=True,
            otp_sent_to=email_clean,
            demo_otp=otp,
            user=UserOut(id=user_id, name=user_name, email=email_clean, is_verified=False, created_at=created_at)
        )

    access_token = create_access_token({"sub": user_id, "email": email_clean})
    refresh_token = create_refresh_token({"sub": user_id, "email": email_clean})

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
        samesite="lax",
        secure=False
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        require_otp=False,
        user=UserOut(id=user_id, name=user_name, email=email_clean, is_verified=True, created_at=created_at)
    )


@router.post("/google", response_model=TokenResponse)
async def google_auth(request: GoogleAuthRequest, response: Response, db: Session = Depends(get_db)):
    """Authenticate or register user via Google OAuth 2.0. Requires OTP verification for first-time users."""
    email_clean = request.email.lower().strip()
    user_doc, user = await _get_user_by_email(email_clean, db)
    name = request.name.strip() if request.name else email_clean.split("@")[0]

    if not user_doc and not user:
        # First-time Google user - initiate OTP verification
        otp = generate_otp_code()
        expires = datetime.now(timezone.utc) + timedelta(minutes=10)
        pwd = hash_password(f"GoogleOAuth2Secured_{email_clean}")
        user_id = str(uuid.uuid4())
        try:
            user_doc = UserDoc(
                id=user_id,
                name=name,
                email=email_clean,
                password_hash=pwd,
                is_verified=False,
                otp_code=otp,
                otp_expires_at=expires
            )
            await user_doc.insert()
        except Exception:
            user_doc = None

        try:
            user = User(
                id=user_id,
                name=name,
                email=email_clean,
                password_hash=pwd,
                is_verified=False,
                otp_code=otp,
                otp_expires_at=expires
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        except Exception:
            pass

        return TokenResponse(
            require_otp=True,
            otp_sent_to=email_clean,
            demo_otp=otp,
            user=UserOut(id=user_id, name=name, email=email_clean, is_verified=False, created_at=datetime.now(timezone.utc))
        )

    user_obj = user_doc if user_doc is not None else user
    assert user_obj is not None

    is_verified = _get_bool(user_obj.is_verified)
    user_id = _get_str(user_obj.id)
    user_name = _get_str(user_obj.name) or name
    created_at = _get_dt(user_obj.created_at)

    if not is_verified:
        otp = generate_otp_code()
        exp = datetime.now(timezone.utc) + timedelta(minutes=10)
        if user_doc is not None:
            user_doc.otp_code = otp
            user_doc.otp_expires_at = exp
            await user_doc.save()
        if user is not None:
            setattr(user, "otp_code", otp)
            setattr(user, "otp_expires_at", exp)
            db.commit()
        return TokenResponse(
            require_otp=True,
            otp_sent_to=email_clean,
            demo_otp=otp,
            user=UserOut(id=user_id, name=user_name, email=email_clean, is_verified=False, created_at=created_at)
        )

    access_token = create_access_token({"sub": user_id, "email": email_clean})
    refresh_token = create_refresh_token({"sub": user_id, "email": email_clean})

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
        samesite="lax",
        secure=False
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        require_otp=False,
        user=UserOut(id=user_id, name=user_name, email=email_clean, is_verified=True, created_at=created_at)
    )


@router.post("/verify-otp", response_model=TokenResponse)
async def verify_otp(request: OTPVerifyRequest, response: Response, db: Session = Depends(get_db)):
    """Verify 6-digit OTP for first-time user email verification."""
    email_clean = request.email.lower().strip()
    user_doc, user = await _get_user_by_email(email_clean, db)
    if not user_doc and not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User account not found.")

    user_obj = user_doc if user_doc is not None else user
    assert user_obj is not None

    is_verified = _get_bool(user_obj.is_verified)
    user_id = _get_str(user_obj.id)
    user_name = _get_str(user_obj.name)
    created_at = _get_dt(user_obj.created_at)

    if not is_verified:
        now_utc = datetime.now(timezone.utc)
        raw_otp_code = getattr(user_obj, "otp_code", None)
        otp_code = _get_str(raw_otp_code) if raw_otp_code else None
        
        raw_otp_exp = getattr(user_obj, "otp_expires_at", None)
        otp_exp = _get_dt(raw_otp_exp) if raw_otp_exp else None
        if otp_exp and otp_exp.tzinfo is None:
            otp_exp = otp_exp.replace(tzinfo=timezone.utc)

        is_valid_otp = (
            (settings.DEMO_MODE and request.otp == "123456") or
            (otp_code is not None and otp_code == request.otp and otp_exp is not None and otp_exp > now_utc)
        )

        if not is_valid_otp:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired OTP code. Please check your email or request a new code."
            )

        if user_doc is not None:
            user_doc.is_verified = True
            user_doc.otp_code = None
            user_doc.otp_expires_at = None
            await user_doc.save()
        if user is not None:
            setattr(user, "is_verified", True)
            setattr(user, "otp_code", None)
            setattr(user, "otp_expires_at", None)
            db.commit()

    access_token = create_access_token({"sub": user_id, "email": email_clean})
    refresh_token = create_refresh_token({"sub": user_id, "email": email_clean})

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
        samesite="lax",
        secure=False
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        require_otp=False,
        user=UserOut(id=user_id, name=user_name, email=email_clean, is_verified=True, created_at=created_at)
    )


@router.post("/resend-otp", response_model=TokenResponse)
async def resend_otp(request: OTPResendRequest, db: Session = Depends(get_db)):
    """Resend a fresh 6-digit OTP code to user's email."""
    email_clean = request.email.lower().strip()
    user_doc, user = await _get_user_by_email(email_clean, db)
    if not user_doc and not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User account not found.")

    user_obj = user_doc if user_doc is not None else user
    assert user_obj is not None

    is_verified = _get_bool(user_obj.is_verified)
    user_id = _get_str(user_obj.id)
    user_name = _get_str(user_obj.name)
    created_at = _get_dt(user_obj.created_at)

    if is_verified:
        return TokenResponse(require_otp=False, user=UserOut(id=user_id, name=user_name, email=email_clean, is_verified=True, created_at=created_at))

    otp = generate_otp_code()
    exp = datetime.now(timezone.utc) + timedelta(minutes=10)
    if user_doc is not None:
        user_doc.otp_code = otp
        user_doc.otp_expires_at = exp
        await user_doc.save()
    if user is not None:
        setattr(user, "otp_code", otp)
        setattr(user, "otp_expires_at", exp)
        db.commit()

    return TokenResponse(
        require_otp=True,
        otp_sent_to=email_clean,
        demo_otp=otp,
        user=UserOut(id=user_id, name=user_name, email=email_clean, is_verified=False, created_at=created_at)
    )


@router.post("/logout")
def logout_user(response: Response):
    """Clear refresh token cookies and end session."""
    response.delete_cookie(key="refresh_token")
    return {"success": True, "message": "Successfully logged out."}


@router.post("/refresh")
async def refresh_token_endpoint(refresh_token: Optional[str] = None, response: Response = Response(), db: Session = Depends(get_db)):
    """Issue a new access token using a valid refresh token."""
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token required.")

    payload = decode_token(refresh_token, settings.JWT_REFRESH_SECRET)
    user_id = str(payload.get("sub"))

    user_doc: Optional[UserDoc] = None
    try:
        user_doc = await UserDoc.find_one(UserDoc.id == user_id)
    except Exception:
        pass

    user: Optional[User] = None
    if not user_doc and db:
        user = db.query(User).filter(User.id == user_id).first()

    user_obj = user_doc if user_doc is not None else user
    if not user_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    email = _get_str(user_obj.email)
    new_access_token = create_access_token({"sub": user_id, "email": email})
    return {"access_token": new_access_token, "token_type": "bearer"}


@router.get("/me", response_model=UserOut)
def get_current_user_profile(current_user: Any = Depends(get_current_user)):
    """Retrieve currently authenticated user profile."""
    return UserOut(
        id=_get_str(getattr(current_user, "id", "")),
        name=_get_str(getattr(current_user, "name", "")),
        email=_get_str(getattr(current_user, "email", "")),
        is_verified=_get_bool(getattr(current_user, "is_verified", True)),
        created_at=_get_dt(getattr(current_user, "created_at", None))
    )
