from fastapi import FastAPI, Depends, HTTPException, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import inspect, text
from typing import List, Optional
from contextlib import asynccontextmanager
import asyncio
import os
import shutil
import uuid
import csv
import io
from datetime import datetime

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

@app.get("/export-csv/")
def export_csv(currency: Optional[str] = None, year: Optional[str] = None, month: Optional[str] = None, db: Session = Depends(get_db)):
    """
    Export transactions as CSV.
    Optional filters:
    - currency: CNY, HKD, USDT
    - year: YYYY
    - month: MM (requires year)
    """
    query = db.query(models.Transaction).order_by(models.Transaction.created_at.desc())
    
    if currency:
        query = query.filter(models.Transaction.currency == currency)
    
    if year:
        # SQLite uses strftime, Postgres uses extract or date_part
        # For compatibility and simplicity, we filter in python or use simple string matching if created_at is string
        # Assuming created_at is DateTime object in SQLAlchemy
        
        # Using SQLAlchemy extract for portability (works on both generally)
        from sqlalchemy import extract
        query = query.filter(extract('year', models.Transaction.created_at) == int(year))
        
        if month:
            query = query.filter(extract('month', models.Transaction.created_at) == int(month))

    transactions = query.all()

    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow(['ID', '时间', '记账人', '金额', '币种', '类别', '项目', '备注', '票据路径'])
    
    # Write data
    for t in transactions:
        # Convert UTC to Beijing Time for export (add 8 hours)
        # created_at is naive datetime in UTC usually, or timezone aware
        # Assuming it's naive UTC stored in DB
        
        # Simple adjustment: just add 8 hours to the object if it exists
        beijing_time = ""
        if t.created_at:
             # If it's naive, assume UTC. If aware, convert.
             # Simplified: just format it. The frontend handles display, here we output raw or adjusted?
             # User asked for "download to local", usually prefers Beijing time.
             # Let's do a safe string format.
             dt = t.created_at
             # dt is datetime object
             import datetime as dt_module
             beijing_dt = dt + dt_module.timedelta(hours=8)
             beijing_time = beijing_dt.strftime('%Y-%m-%d %H:%M:%S')

        writer.writerow([
            t.id,
            beijing_time,
            t.user_name,
            t.amount,
            t.currency,
            t.category,
            t.item,
            t.raw_text,
            t.receipt_image_path or ""
        ])
    
    output.seek(0)
    
    # Filename
    filename_parts = ["transactions"]
    if currency: filename_parts.append(currency)
    if year: filename_parts.append(year)
    if month: filename_parts.append(month)
    filename = "_".join(filename_parts) + ".csv"
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.delete("/transactions/reset")
def reset_transactions(db: Session = Depends(get_db)):
    try:
        num_deleted = db.query(models.Transaction).delete()
        db.commit()
        return {"message": f"Deleted {num_deleted} transactions"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
