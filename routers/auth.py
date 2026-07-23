from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
import model
from database import get_db
from security import hash_password, verify_password, create_access_token
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])

class UserCreate(BaseModel):
    username: str
    password: str

class LoginRequest(BaseModel):
    username: str
    password: str

@router.post("/register", status_code=status.HTTP_201_CREATED)
def create_admin_user(user_data: UserCreate, db: Session = Depends(get_db)):
    existing_user = db.query(model.User).filter(model.User.username == user_data.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    
    hashed = hash_password(user_data.password)
    new_user = model.User(username=user_data.username, hashed_password=hashed)
    db.add(new_user)
    db.commit()
    return {"message": "Admin user created successfully"}

@router.post("/login")
def login_admin(credentials: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(model.User).filter(model.User.username == credentials.username).first()
    
    if not user or not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
        
    token_data = {"sub": user.username}
    access_token = create_access_token(data=token_data)
    
   
    return {"Authorization": f"Bearer {access_token}"}