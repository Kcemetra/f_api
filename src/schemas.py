from pydantic import BaseModel, HttpUrl
from typing import Optional
from datetime import datetime
import uuid
from fastapi_users import schemas


class UserRead(schemas.BaseUser[uuid.UUID]):
    pass

class UserCreate(schemas.BaseUserCreate):
    pass

class LinkCreate(BaseModel):
    original_url: HttpUrl
    custom_alias: Optional[str] = None
    expires_at: Optional[datetime] = None

class LinkUpdate(BaseModel):
    original_url: HttpUrl

class LinkResponse(BaseModel):
    short_code: str
    original_url: str
    expires_at: Optional[datetime]

class LinkStats(BaseModel):
    original_url: str
    created_at: datetime
    clicks_count: int
    last_clicked: Optional[datetime]

class ProfileLink(BaseModel):
    short_code: str
    original_url: str
    expires_at: Optional[datetime]

class ProfileResponse(BaseModel):
    email: str
    active_links: list[ProfileLink]

class BulkUpdateLinks(BaseModel):
    original_url: str = "leave_as_is"
    expires_at: Optional[datetime] = None