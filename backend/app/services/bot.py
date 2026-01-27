import os
import asyncio
from telegram import Update, ForceReply
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from sqlalchemy.orm import Session
from ..database import SessionLocal
from .. import models
from .llm import parse_expense_text, parse_expense_image, translate_to_chinese

# 获取 Token
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

def set_state(user_id: str, data: dict):
    db: Session = SessionLocal()
    try:
        state = db.query(models.BotState).filter(models.BotState.user_id == user_id).first()
        if not state:
            state = models.BotState(user_id=user_id, data=data)
            db.add(state)
        else:
            state.data = data
        db.commit()
    except Exception as e:
        print(f"Error setting state: {e}")
        db.rollback()
    finally:
        db.close()

def get_state(user_id: str) -> dict | None:
    db: Session = SessionLocal()
    try:
        state = db.query(models.BotState).filter(models.BotState.user_id == user_id).first()
        if state:
            data = state.data
            # Optional: auto-clear state after read, or keep it until explicitly cleared
            # Here we follow PENDING.pop() pattern: read and clear
            db.delete(state)
            db.commit()
            return data
        return None
    except Exception as e:
        print(f"Error getting state: {e}")
        db.rollback()
        return None
    finally:
        db.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="👋 嗨！我是你的家庭记账助手。\n请直接发送消费内容，例如：\n'买菜 200 HKD' 或 '打车 50' (默认 CNY)\n也可以直接发送小票图片！"
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_name = update.effective_user.first_name
    
    # Check if this is a photo
    if not update.message.photo:
        return

    # Get the largest photo
    photo = update.message.photo[-1]
    
    # Send processing message
    status_msg = await context.bot.send_message(
        chat_id=update.effective_chat.id, 
        text="�️ 收到图片，正在识别..."
    )

    try:
        # Save to uploads directory permanently
        file = await context.bot.get_file(photo.file_id)
        
        # Use env var for upload dir
        upload_dir = os.getenv("UPLOAD_DIR", "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        
        # Use file_id as filename to avoid collisions
        filename = f"{photo.file_id}.jpg"
        file_path = os.path.join(upload_dir, filename)
        
        await file.download_to_drive(file_path)
        
        # Parse image (OCR + LLM)
        # Pass absolute path for safety, though relative should work
        result = await asyncio.to_thread(parse_expense_image, os.path.abspath(file_path))
        
        if not result.get("is_expense"):
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=status_msg.message_id,
                text=f"🤔 无法识别为账单。{result.get('error', '')}"
            )
            # Optional: Delete file if not expense? Keep for now just in case.
            return
            
        # Store relative path for frontend access
        # The frontend expects "uploads/filename.jpg" to append to API_URL
        relative_path = f"uploads/{filename}"

        # Store state
        set_state(user_id, {
            "user_id": user_id,
            "user_name": user_name,
            "amount": result["amount"],
            "currency": result["currency"],
            "category": result["category"],
            "item": result.get("item") or "消费",
            "raw_text": "[Image Receipt]",
            "receipt_image_path": relative_path, 
            "created_at": result.get("created_at")
        })
        
        prompt = (
            f"预览：{result['amount']} {result['currency']}，{result['category']}\n"
            f"请回复本次消费的项目（例如：转账给XX、在XX购物）"
        )
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=status_msg.message_id,
            text="图片识别完成，等待填写项目..."
        )
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=prompt,
            reply_markup=ForceReply(selective=True)
        )
                
    except Exception as e:
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=status_msg.message_id,
            text=f"❌ 图片处理出错: {str(e)}"
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    user_id = str(update.effective_user.id)
    user_name = update.effective_user.first_name
    
    pending_data = get_state(user_id)
    if pending_data:
        data = pending_data
        item_text = user_text.strip()
        try:
            translated_item = await asyncio.to_thread(translate_to_chinese, item_text)
            if translated_item:
                item_text = translated_item
        except Exception as e:
            print(f"Translation failed: {e}")
        db: Session = SessionLocal()
        try:
            new_tx = models.Transaction(
                user_id=data["user_id"],
                user_name=data["user_name"],
                amount=data["amount"],
                currency=data["currency"],
                category=data["category"],
                item=item_text or data.get("item") or "消费",
                raw_text=data["raw_text"],
                receipt_image_path=data.get("receipt_image_path"),
                created_at=data.get("created_at")
            )
            db.add(new_tx)
            db.commit()
            db.refresh(new_tx)
            reply_text = (
                f"✅ 已记录 #{new_tx.id}\n"
                f"💰 {data['amount']} {data['currency']}\n"
                f"📂 {data['category']} - {item_text or '消费'}\n\n"
                f"操作：/undo 撤回最近一条；/delete {new_tx.id} 删除；/edit {new_tx.id} 新项目名"
            )
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=reply_text,
                parse_mode='Markdown'
            )
            return
        except Exception as e:
            db.rollback()
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ 保存失败: {str(e)}"
            )
            return
        finally:
            db.close()

    # 1. 调用 LLM 解析
    status_msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="⏳ 正在分析...")
    try:
        result = await asyncio.to_thread(parse_expense_text, user_text)
        if not result.get("is_expense"):
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=status_msg.message_id,
                text="🤔 这看起来不像是一笔账单。请再说具体点？"
            )
            return
        set_state(user_id, {
            "user_id": user_id,
            "user_name": user_name,
            "amount": result["amount"],
            "currency": result["currency"],
            "category": result["category"],
            "item": result.get("item") or "消费",
            "raw_text": user_text
        })
        prompt = (
            f"预览：{result['amount']} {result['currency']}，{result['category']}\n"
            f"请回复本次消费的项目（例如：转账给XX、在XX购物）"
        )
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=status_msg.message_id,
            text="文本识别完成，等待填写项目..."
        )
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=prompt,
            reply_markup=ForceReply(selective=True)
        )
    except Exception as e:
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=status_msg.message_id,
            text=f"❌ 处理出错: {str(e)}"
        )

async def undo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    db: Session = SessionLocal()
    try:
        tx = db.query(models.Transaction).filter(models.Transaction.user_id == user_id).order_by(models.Transaction.created_at.desc()).first()
        if not tx:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="没有可撤回的记录")
            return
        db.delete(tx)
        db.commit()
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"已撤回记录 #{tx.id}")
    except Exception as e:
        db.rollback()
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"撤回失败: {str(e)}")
    finally:
        db.close()

async def delete_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    args = context.args if hasattr(context, "args") else []
    if not args:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="用法: /delete 记录ID")
        return
    try:
        tid = int(args[0])
    except:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="记录ID必须是数字")
        return
    db: Session = SessionLocal()
    try:
        tx = db.query(models.Transaction).filter(models.Transaction.id == tid, models.Transaction.user_id == user_id).first()
        if not tx:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="未找到该记录或无权限删除")
            return
        db.delete(tx)
        db.commit()
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"已删除记录 #{tid}")
    except Exception as e:
        db.rollback()
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"删除失败: {str(e)}")
    finally:
        db.close()

async def edit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    args = context.args if hasattr(context, "args") else []
    if len(args) < 2:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="用法: /edit 记录ID 新项目名")
        return
    try:
        tid = int(args[0])
    except:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="记录ID必须是数字")
        return
    new_item = " ".join(args[1:]).strip()
    if not new_item:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="新项目名不能为空")
        return
    try:
        translated_item = await asyncio.to_thread(translate_to_chinese, new_item)
        if translated_item:
            new_item = translated_item
    except Exception as e:
        print(f"Translation failed: {e}")
    db: Session = SessionLocal()
    try:
        tx = db.query(models.Transaction).filter(models.Transaction.id == tid, models.Transaction.user_id == user_id).first()
        if not tx:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="未找到该记录或无权限修改")
            return
        tx.item = new_item
        db.commit()
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"已更新记录 #{tid} 项目为：{new_item}")
    except Exception as e:
        db.rollback()
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"修改失败: {str(e)}")
    finally:
        db.close()

async def handle_item_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    pending_data = get_state(user_id)
    if not pending_data:
        return
    item_text = update.message.text.strip()
    
    # Translate item to Chinese if needed
    try:
        translated_item = await asyncio.to_thread(translate_to_chinese, item_text)
        if translated_item:
            item_text = translated_item
    except Exception as e:
        print(f"Translation failed: {e}")
        
    data = pending_data
    db: Session = SessionLocal()
    try:
        new_tx = models.Transaction(
            user_id=data["user_id"],
            user_name=data["user_name"],
            amount=data["amount"],
            currency=data["currency"],
            category=data["category"],
            item=item_text,
            raw_text=data["raw_text"],
            receipt_image_path=data.get("receipt_image_path"),
            created_at=data.get("created_at")
        )
        db.add(new_tx)
        db.commit()
        db.refresh(new_tx)
        reply_text = (
            f"✅ 已记录 #{new_tx.id}\n"
            f"💰 {data['amount']} {data['currency']}\n"
            f"📂 {data['category']} - {item_text}\n\n"
            f"操作：/undo 撤回最近一条；/delete {new_tx.id} 删除；/edit {new_tx.id} 新项目名"
        )
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=reply_text,
            parse_mode='Markdown'
        )
    except Exception as e:
        db.rollback()
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ 保存失败: {str(e)}"
        )
    finally:
        db.close()
def create_bot_app():
    if not TELEGRAM_BOT_TOKEN:
        print("Telegram Token not set, bot will not run.")
        return None
    
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    start_handler = CommandHandler('start', start)
    msg_handler = MessageHandler(filters.TEXT & (~filters.COMMAND) & (~filters.REPLY), handle_message)
    photo_handler = MessageHandler(filters.PHOTO, handle_photo)
    reply_handler = MessageHandler(filters.TEXT & filters.REPLY, handle_item_reply)
    undo_handler = CommandHandler('undo', undo)
    delete_handler = CommandHandler('delete', delete_cmd)
    edit_handler = CommandHandler('edit', edit_cmd)
    
    application.add_handler(start_handler)
    application.add_handler(photo_handler)
    application.add_handler(msg_handler)
    application.add_handler(reply_handler)
    application.add_handler(undo_handler)
    application.add_handler(delete_handler)
    application.add_handler(edit_handler)
    application.add_handler(msg_handler)
    
    return application
