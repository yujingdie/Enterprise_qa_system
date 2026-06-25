"""
JWT 签发与验证
"""

from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
from passlib.context import CryptContext
from app.core.config import config

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """密码哈希"""
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """验证密码"""
    return pwd_context.verify(plain, hashed)


def create_access_token(user_id: str) -> str:
    """签发 JWT Token"""
    expire = datetime.now(timezone.utc) + timedelta(minutes=config.env.jwt_expire_minutes)
    payload = {
        "sub": user_id,
        "exp": expire,
    }
    return jwt.encode(payload, config.env.jwt_secret, algorithm=config.env.jwt_algorithm)


def verify_token(token: str) -> str | None:
    """验证 JWT Token，成功返回 user_id，失败返回 None"""
    try:
        payload = jwt.decode(token, config.env.jwt_secret, algorithms=[config.env.jwt_algorithm])
        return payload.get("sub")
    except JWTError:
        return None
