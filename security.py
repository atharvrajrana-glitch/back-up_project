import os
import jwt
from dotenv import load_dotenv
from datetime import datetime , timedelta ,timezone
from passlib.context import CryptContext

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")
ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES")
)

pwd_context = CryptContext(schemes=["bcrypt"],deprecated="auto")

def hash_password(password:str)-> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str , hashed_password:str) -> Bool:
    return pwd_context.verify(plain_password,hashed_password)

def create_access_token(data:dict)-> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp":expire})

    encoder_jwt = jwt.encode(to_encode ,SECRET_KEY, algorithm=ALGORITHM)
    return encoder_jwt
