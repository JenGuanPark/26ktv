from fastapi import FastAPI, Depends, HTTPException, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import inspect, text
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

def ensure_columns():
    """Check if receipt_image_path column exists in transactions table, if not add it."""
    inspector = inspect(engine)
    columns = [c['name'] for c in inspector.get_columns('transactions')]
    if 'receipt_image_path' not in columns:
        print("Migrating database: Adding receipt_image_path column...")
        with engine.connect() as conn:
            # Check database type to determine correct SQL syntax
            if 'sqlite' in str(engine.url):
                conn.execute(text("ALTER TABLE transactions ADD COLUMN receipt_image_path VARCHAR"))
            else:
                # Postgres (Render)
                conn.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS receipt_image_path VARCHAR"))
            conn.commit()
        print("Migration complete.")

bot_app = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    print("Backend started...")
    
    # Run DB migration check
    try:
        ensure_columns()
    except Exception as e:
        print(f"Migration warning: {e}")
    
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
    if not file_extension:
        file_extension = ".jpg" # Default to jpg if no extension
        
    filename = f"{uuid.uuid4()}{file_extension}"
    file_path = os.path.join(UPLOAD_DIR, filename)
    
    # Save file
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")
        
    # Update transaction
    # Store relative path for frontend access via mounted static route
    # e.g., if UPLOAD_DIR is /var/data/uploads, we want to store "uploads/filename.jpg"
    # But wait, app.mount("/uploads") means http://host/uploads/filename.jpg maps to UPLOAD_DIR/filename.jpg
    # So we should store just "uploads/{filename}" in the DB so frontend can prepend API_URL
    
    relative_path = f"uploads/{filename}"
    transaction.receipt_image_path = relative_path
    db.commit()
    db.refresh(transaction)
    
    return {"filename": filename, "file_path": relative_path}

@app.delete("/transactions/reset")
def reset_transactions(db: Session = Depends(get_db)):
    try:
        num_deleted = db.query(models.Transaction).delete()
        db.commit()
        return {"message": f"Deleted {num_deleted} transactions"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
