from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class TransactionBase(BaseModel):
    amount: float
    currency: str
    category: str
    item: str
    raw_text: Optional[str] = None
    user_id: str
    user_name: str

class TransactionCreate(TransactionBase):
    pass

class Transaction(TransactionBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True
