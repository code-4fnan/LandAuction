from sqlalchemy import Column, Integer, String, Boolean
from src.db.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    
    # We NEVER store plain-text passwords, only the hashed versions
    hashed_password = Column(String, nullable=False)
    
    # A simple flag to disable malicious accounts if needed
    is_active = Column(Boolean, default=True)