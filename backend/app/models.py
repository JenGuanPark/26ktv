from sqlalchemy import Column, Integer, String, Float, DateTime, JSON
from datetime import datetime
from .database import Base

class BotState(Base):
    __tablename__ = "bot_states"
    
    user_id = Column(String, primary_key=True, index=True)
    data = Column(JSON, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True) # Telegram User ID
    user_name = Column(String)           # Telegram User Name/Display Name
    
    amount = Column(Float, nullable=False)
    currency = Column(String, nullable=False) # 'CNY' or 'HKD'
    category = Column(String, index=True)     # e.g., 'Food', 'Transport'
    item = Column(String)                     # Description of the item
    
    raw_text = Column(String)                 # Original message text
    created_at = Column(DateTime, default=datetime.now)
