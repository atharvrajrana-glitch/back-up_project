import os
from dotenv import load_dotenv
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader  
from sqlalchemy.orm import Session
from database import get_db
import model
load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")
ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES")
)

api_key_scheme = APIKeyHeader(name="Authorization", auto_error=False)

def get_current_admin(token: str = Depends(api_key_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials or token expired",
    )
    
    if not token:
        raise credentials_exception
        
    try:
        # If the token contains "Bearer ", strip it out to get the raw JWT
        if token.startswith("Bearer "):
            raw_token = token.split(" ")[1]
        else:
            raw_token = token

        payload = jwt.decode(raw_token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        
        if username is None:
            raise credentials_exception
            
    except jwt.PyJWTError:
        raise credentials_exception

    user = db.query(model.User).filter(model.User.username == username).first()
    if user is None:
        raise credentials_exception
        
    return user