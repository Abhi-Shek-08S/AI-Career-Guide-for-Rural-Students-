from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime
import uuid


class User(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    email: EmailStr
    full_name: str
    hashed_password: str
    phone: Optional[str] = None
    location: Optional[str] = None
    education_level: Optional[str] = None
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login: Optional[datetime] = None


class UserRegister(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    phone: Optional[str] = None
    location: Optional[str] = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str
    user: dict


class Feedback(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    recommendation_id: str
    rating: int  # 1-5
    comments: Optional[str] = None
    is_helpful: bool
    suggestions: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class FeedbackCreate(BaseModel):
    recommendation_id: str
    rating: int
    comments: Optional[str] = None
    is_helpful: bool
    suggestions: Optional[str] = None
