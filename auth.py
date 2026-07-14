from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from database import get_db
import models
import schemas

# Security configuration
SECRET_KEY = "eoct-secret-key-2024-fastapi-react-application"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480  # 8 hours

security = HTTPBearer()

def verify_password(plain_password: str, stored_password: str) -> bool:
    # PLAIN TEXT PASSWORD COMPARISON (NO HASHING)
    return plain_password == stored_password

def get_password_hash(password: str) -> str:
    # Return password as-is (NO HASHING)
    return password

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def decode_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        employee_id: str = payload.get("sub")
        if employee_id is None:
            return None
        return employee_id
    except JWTError:
        return None

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    token = credentials.credentials
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    employee_id = decode_token(token)
    if employee_id is None:
        raise credentials_exception
    
    user = db.query(models.User).filter(models.User.employee_id == employee_id).first()
    if user is None:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive"
        )
    return user

def authenticate_user(db: Session, employee_id: str, password: str):
    user = db.query(models.User).filter(models.User.employee_id == employee_id).first()
    if not user:
        return False
    if not verify_password(password, user.password):
        return False
    return user
