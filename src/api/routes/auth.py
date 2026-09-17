from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from src.db.database import get_db
from src.models.user import User
# FIX: Added verify_password to the import list below
from src.api.security import get_password_hash, verify_password 

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

# The expected JSON format for registration
class UserCreate(BaseModel):
    username: str
    email: str
    password: str

@router.post("/register")
async def register_user(user: UserCreate, db: AsyncSession = Depends(get_db)):
    # 1. Check if the username already exists
    query = select(User).where(User.username == user.username)
    result = await db.execute(query)
    existing_user = result.scalar_one_or_none()
    
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already taken")

    # 2. Hash the password
    hashed_pwd = get_password_hash(user.password)

    # 3. Create the new user profile
    new_user = User(
        username=user.username,
        email=user.email,
        hashed_password=hashed_pwd
    )
    
    # 4. Save them to the database
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    
    return {"message": "User registered successfully", "user_id": new_user.id}

# The expected JSON format for logging in (no email required)
class UserLogin(BaseModel):
    username: str
    password: str

@router.post("/login")
async def login_user(user: UserLogin, db: AsyncSession = Depends(get_db)):
    # 1. Find the user in the database
    query = select(User).where(User.username == user.username)
    result = await db.execute(query)
    db_user = result.scalar_one_or_none()
    
    # 2. Check if user exists AND password is correct
    if not db_user or not verify_password(user.password, db_user.hashed_password):
        raise HTTPException(status_code=400, detail="Invalid username or password")
        
    return {"message": "Login successful", "username": db_user.username}