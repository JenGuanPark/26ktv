from fastapi import FastAPI, Depends, HTTPException, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from typing import List
from contextlib import asynccontextmanager
import asyncio
import os
import shutil
import uuid

from . import models, schemas, database
from .database import engine, get_db
from .services.bot import create_bot_app

# Create tables
models.Base.metadata.create_all(bind=engine)

# Ensure uploads directory exists
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

bot_app = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    print("Backend started...")
    
    global bot_app
    bot_app = create_bot_app()
    if bot_app:
        print("Starting Telegram Bot...")
        await bot_app.initialize()
        await bot_app.start()
        await bot_app.updater.start_polling()
    else:
        print("Telegram Bot Token not set, skipping bot startup.")

    yield
    
    # Shutdown logic
    if bot_app:
        print("Stopping Telegram Bot...")
        await bot_app.updater.stop()
        await bot_app.stop()
        await bot_app.shutdown()
        
    print("Backend stopped...")

app = FastAPI(lifespan=lifespan)

# Mount uploads directory
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Family Ledger API is running"}

@app.get("/transactions/", response_model=List[schemas.Transaction])
def read_transactions(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    transactions = db.query(models.Transaction).order_by(models.Transaction.created_at.desc()).offset(skip).limit(limit).all()
    return transactions

@app.post("/transactions/", response_model=schemas.Transaction)
def create_transaction(transaction: schemas.TransactionCreate, db: Session = Depends(get_db)):
    db_transaction = models.Transaction(**transaction.dict())
    db.add(db_transaction)
    db.commit()
    db.refresh(db_transaction)
    return db_transaction

@app.post("/transactions/{transaction_id}/upload-receipt")
async def upload_receipt(transaction_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    transaction = db.query(models.Transaction).filter(models.Transaction.id == transaction_id).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    # Generate unique filename
    file_extension = os.path.splitext(file.filename)[1]
    filename = f"{uuid.uuid4()}{file_extension}"
    file_path = os.path.join(UPLOAD_DIR, filename)
    
    # Save file
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # Update transaction
    transaction.receipt_image_path = file_path
    db.commit()
    db.refresh(transaction)
    
    return {"filename": filename, "file_path": file_path}

@app.delete("/transactions/reset")
def reset_transactions(db: Session = Depends(get_db)):
    try:
        num_deleted = db.query(models.Transaction).delete()
        db.commit()
        return {"message": f"Deleted {num_deleted} transactions"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
