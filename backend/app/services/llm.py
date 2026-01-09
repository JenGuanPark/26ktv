import os
import json
import re
import requests
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# Text Model (DeepSeek or OpenAI)
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
BASE_URL = "https://api.deepseek.com" if os.getenv("DEEPSEEK_API_KEY") else None

# OCR.space Configuration
OCR_SPACE_API_KEY = os.getenv("OCR_SPACE_KEY", "K87916702088957")

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=BASE_URL)

SYSTEM_PROMPT = """
You are a smart expense tracking assistant for a family living in both Mainland China and Hong Kong.
Your task is to extract expense details from the user's natural language input.

The user maintains two separate ledgers:
1. **CNY (RMB)**: Default for expenses in Mainland China or when no currency is specified.
2. **HKD**: For expenses in Hong Kong.

Please extract the following fields in JSON format:
- amount: (number) The numerical value.
- currency: (string) "CNY" or "HKD".
- category: (string) A short category name in Simplified Chinese (e.g., "餐饮", "交通", "购物", "居住", "娱乐", "医疗", "其他").
- item: (string) A brief description in Simplified Chinese. If the original text is in English or other languages, TRANSLATE it to Simplified Chinese.

### Currency Inference Rules:
1. **Explicit Currency**: If the user mentions "港币", "HKD", "HK$", "港纸", set currency to "HKD". If "人民币", "RMB", "CNY", "元", set to "CNY".
2. **Contextual Inference**:
   - If the item/location implies Hong Kong (e.g., "MTR", "旺角", "茶餐厅", "八达通", "7-11 HK", English receipts from HK stores), default to **HKD**.
   - If the item/location implies Mainland China (e.g., "微信支付", "支付宝", "淘宝", "美团", "滴滴", Simplified Chinese receipts), default to **CNY**.
3. **Default**: If no currency is specified and no context is found, default to **CNY**.

### Examples:
- "买菜 200" -> {"amount": 200, "currency": "CNY", "category": "餐饮", "item": "买菜"}
- "Taxi 50" -> {"amount": 50, "currency": "CNY", "category": "交通", "item": "出租车"} (Ambiguous, default to CNY)
- "打车去旺角 80" -> {"amount": 80, "currency": "HKD", "category": "交通", "item": "打车去旺角"}
- "7-11买水 10块" -> {"amount": 10, "currency": "CNY", "category": "餐饮", "item": "7-11买水"}
- "午饭 500 港币" -> {"amount": 500, "currency": "HKD", "category": "餐饮", "item": "午饭"}

Rules:
- If input is not an expense, return {"is_expense": false}.
- Return JSON only.
- ALWAYS return 'item' and 'category' in Simplified Chinese.
"""

def _simple_parse(text: str):
    lower = text.lower()
    currency = "CNY"
    if any(tok in lower for tok in ["hkd", "港币", "港元", "港幣", "港紙", "蚊"]):
        currency = "HKD"
    if any(tok in lower for tok in ["cny", "人民币", "rmb"]):
        currency = "CNY"
    if ("块" in text) or ("元" in text):
        currency = "CNY"
    m = re.search(r"([0-9]+(?:\\.[0-9]+)?)", text)
    if not m:
        return None
    amount = float(m.group(1))
    category = "其他"
    if any(kw in text for kw in ["充值", "会员", "充值值", "会员费"]):
        category = "其他"
    elif any(kw in text for kw in ["餐", "饭", "早餐", "午饭", "晚餐", "买菜", "超市"]):
        category = "餐饮"
    elif any(kw in text for kw in ["打车", "出租", "交通", "地铁", "公交", "的士", "巴士", "MTR", "mtr"]):
        category = "交通"
    item = text.strip()
    return {"is_expense": True, "amount": amount, "currency": currency, "category": category, "item": item}

def parse_expense_text(text: str):
    if not DEEPSEEK_API_KEY:
        fallback = _simple_parse(text)
        if fallback:
            return fallback
        return {"is_expense": False, "error": "NO_API_KEY"}

    try:
        response = client.chat.completions.create(
            model="deepseek-chat" if BASE_URL else "gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text}
            ],
            response_format={ "type": "json_object" }
        )
        
        content = response.choices[0].message.content
        parsed = json.loads(content)
        
        # Validation and fallback logic
        if not isinstance(parsed, dict):
            fallback = _simple_parse(text)
            return fallback if fallback else {"is_expense": False}
            
        if not parsed.get("is_expense", True): # Default true if not specified
             return {"is_expense": False}
             
        # Ensure essential fields
        if "amount" not in parsed:
            fallback = _simple_parse(text)
            if fallback: parsed["amount"] = fallback["amount"]
        
        if "currency" not in parsed:
            parsed["currency"] = "CNY"
            
        if "item" not in parsed:
            parsed["item"] = text[:20]

        parsed["is_expense"] = True
        return parsed
    except Exception as e:
        print(f"LLM Error: {e}")
        fallback = _simple_parse(text)
        if fallback:
            return fallback
        return {"is_expense": False, "error": str(e)}

def _run_ocr_space(image_path: str) -> str:
    """
    Use OCR.space Free API to extract text from image.
    """
    try:
        url = "https://api.ocr.space/parse/image"
        with open(image_path, 'rb') as f:
            payload = {
                'apikey': OCR_SPACE_API_KEY,
                'language': 'chs', # Chinese Simplified (covers English numbers too)
                'isOverlayRequired': False,
                'OCREngine': 2, # Engine 2 is better for numbers/receipts
                'scale': True
            }
            files = {'file': f}
            # OCR.space free tier can be slow, set timeout generously
            r = requests.post(url, files=files, data=payload, timeout=30)
            r.raise_for_status()
            result = r.json()
            
            if result.get('IsErroredOnProcessing'):
                err_msg = result.get('ErrorMessage')
                print(f"OCR API Error: {err_msg}")
                # Fallback to Engine 1 if Engine 2 fails
                if payload['OCREngine'] == 2:
                    print("Retrying with OCR Engine 1...")
                    f.seek(0)
                    payload['OCREngine'] = 1
                    r = requests.post(url, files=files, data=payload, timeout=30)
                    result = r.json()
                    if result.get('IsErroredOnProcessing'):
                        return ""
                else:
                    return ""

            parsed_results = result.get('ParsedResults')
            if not parsed_results:
                return ""
            
            extracted_text = parsed_results[0].get('ParsedText', "")
            return extracted_text.strip()

    except Exception as e:
        print(f"OCR Request Exception: {e}")
        return ""

def parse_expense_image(image_path: str):
    """
    1. Upload image to OCR.space to get text.
    2. Pass text to parse_expense_text (DeepSeek).
    """
    print(f"Starting OCR for {image_path}...")
    ocr_text = _run_ocr_space(image_path)
    
    if not ocr_text:
        return {"is_expense": False, "error": "Could not extract text from image (OCR failed)."}
    
    print(f"OCR Result: {ocr_text[:100]}...") # Log first 100 chars
    
    # Pass the OCR text to the existing text parser
    return parse_expense_text(ocr_text)
