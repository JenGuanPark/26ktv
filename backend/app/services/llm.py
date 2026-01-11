import os
import json
import base64
import re
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# Configuration
# 优先检查 DASHSCOPE_API_KEY (阿里云)，其次是 OPENAI_API_KEY
API_KEY = os.getenv("DASHSCOPE_API_KEY") or os.getenv("OPENAI_API_KEY")

# 自动判断 Base URL 和 Model
if os.getenv("DASHSCOPE_API_KEY"):
    # 阿里云配置
    BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    VISION_MODEL = "qwen-vl-max" # 通义千问视觉增强版
    TEXT_MODEL = "qwen-plus"     # 通义千问增强版
    print("Using DashScope (Aliyun) models...")
else:
    # OpenAI 默认配置
    BASE_URL = os.getenv("OPENAI_BASE_URL") 
    VISION_MODEL = "gpt-4o" 
    TEXT_MODEL = "gpt-4o-mini"

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

SYSTEM_PROMPT = """
You are a smart expense tracking assistant for a family living in both Mainland China and Hong Kong.
Your task is to extract expense details from the user's natural language input or receipt images.

The user maintains two separate ledgers:
1. **CNY (RMB)**: Default for expenses in Mainland China or when no currency is specified.
2. **HKD**: For expenses in Hong Kong.
3. **USDT**: For cryptocurrency expenses (Tether).

Please extract the following fields in JSON format:
- amount: (number) The numerical value.
- currency: (string) "CNY", "HKD" or "USDT".
- category: (string) A short category name in Simplified Chinese (e.g., "餐饮", "交通", "购物", "居住", "娱乐", "医疗", "其他").
- item: (string) A brief description in Simplified Chinese. If the original text is in English or other languages, TRANSLATE it to Simplified Chinese.

### Currency Inference Rules:
1. **Explicit Currency**: 
   - If "港币", "HKD", "HK$", "港纸", set currency to "HKD". 
   - If "USDT", "Tether", "泰达币", "U", "u", set currency to "USDT".
   - If "人民币", "RMB", "CNY", "元", set to "CNY".
2. **Contextual Inference**:
   - If the item/location implies Hong Kong (e.g., "MTR", "旺角", "茶餐厅", "八达通", "7-11 HK", English receipts from HK stores), default to **HKD**.
   - If the item implies crypto or blockchain (e.g. "Gas fee", "TRX", "ETH", "Binance", "Okx"), default to **USDT**.
   - If the item/location implies Mainland China (e.g., "微信支付", "支付宝", "淘宝", "美团", "滴滴", Simplified Chinese receipts), default to **CNY**.
3. **Default**: If no currency is specified and no context is found, default to **CNY**.

### Examples:
- "买菜 200" -> {"amount": 200, "currency": "CNY", "category": "餐饮", "item": "买菜"}
- "Taxi 50" -> {"amount": 50, "currency": "CNY", "category": "交通", "item": "出租车"} (Ambiguous, default to CNY)
- "打车去旺角 80" -> {"amount": 80, "currency": "HKD", "category": "交通", "item": "打车去旺角"}
- "7-11买水 10块" -> {"amount": 10, "currency": "CNY", "category": "餐饮", "item": "7-11买水"}
- "午饭 500 港币" -> {"amount": 500, "currency": "HKD", "category": "餐饮", "item": "午饭"}
- "Gas fee 10 U" -> {"amount": 10, "currency": "USDT", "category": "其他", "item": "Gas fee"}
- "买U 1000" -> {"amount": 1000, "currency": "USDT", "category": "其他", "item": "买U"}

Rules:
- If input is not an expense, return {"is_expense": false}.
- Return JSON only.
- ALWAYS return 'item' and 'category' in Simplified Chinese.
"""

def _simple_parse(text: str):
    """Fallback regex parser for simple text inputs"""
    lower = text.lower()
    currency = "CNY"
    if any(tok in lower for tok in ["hkd", "港币", "港元", "港幣", "港紙", "蚊"]):
        currency = "HKD"
    if any(tok in lower for tok in ["usdt", "tether", "泰达币"]):
        currency = "USDT"
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
    if not API_KEY:
        fallback = _simple_parse(text)
        if fallback:
            return fallback
        return {"is_expense": False, "error": "NO_API_KEY"}

    try:
        response = client.chat.completions.create(
            model=TEXT_MODEL,
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
        print(f"LLM Text Error: {e}")
        fallback = _simple_parse(text)
        if fallback:
            return fallback
        return {"is_expense": False, "error": str(e)}

def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def parse_expense_image(image_path: str):
    """
    Use GPT-4o Vision to directly understand the receipt image.
    """
    if not API_KEY:
        return {"is_expense": False, "error": "No API Key configured"}

    print(f"Analyzing image with {VISION_MODEL}: {image_path}")
    
    try:
        base64_image = encode_image(image_path)
        
        response = client.chat.completions.create(
            model=VISION_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "这是我的消费小票，请识别其中的金额、币种、类别和商品名称。"},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}",
                                "detail": "high"
                            }
                        }
                    ]
                }
            ],
            response_format={ "type": "json_object" },
            max_tokens=300
        )

        content = response.choices[0].message.content
        parsed = json.loads(content)
        
        if not parsed.get("is_expense", True):
            return {"is_expense": False, "error": "AI recognized this is not an expense receipt."}
            
        # Basic validation
        if "amount" not in parsed:
             return {"is_expense": False, "error": "Could not find amount in image."}
             
        if "currency" not in parsed:
            parsed["currency"] = "CNY" # Default
            
        if "item" not in parsed:
            parsed["item"] = "未知商品"

        parsed["is_expense"] = True
        return parsed

    except Exception as e:
        print(f"LLM Vision Error: {e}")
        return {"is_expense": False, "error": f"Vision API Error: {str(e)}"}
