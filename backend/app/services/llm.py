import os
import json
import re
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
BASE_URL = "https://api.deepseek.com"

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=BASE_URL)

SYSTEM_PROMPT = """
You are a smart expense tracking assistant for a family living in both Mainland China and Hong Kong.
Your task is to extract expense details from the user's natural language input or OCR text from receipts.

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

### Receipt/OCR Handling:
- The input might be raw text extracted from an image (OCR). It may contain noise.
- Look for the **Total Amount** (largest number usually associated with "Total", "Amount", "合计", "实付").
- Ignore dates, times, and transaction IDs unless they help identify the context.
- Summarize the main item purchased.

### Examples:
- "买菜 200" -> {"amount": 200, "currency": "CNY", "category": "餐饮", "item": "买菜"}
- "Taxi 50" -> {"amount": 50, "currency": "CNY", "category": "交通", "item": "出租车"} (Ambiguous, default to CNY)
- "打车去旺角 80" -> {"amount": 80, "currency": "HKD", "category": "交通", "item": "打车去旺角"}
- "7-11买水 10块" -> {"amount": 10, "currency": "CNY", "category": "餐饮", "item": "7-11买水"}
- "午饭 500 港币" -> {"amount": 500, "currency": "HKD", "category": "餐饮", "item": "午饭"}
- (OCR Text) "STARBUCKS COFFEE HK ... Total HKD 45.00" -> {"amount": 45.00, "currency": "HKD", "category": "餐饮", "item": "星巴克咖啡"}

Rules:
- If input is not an expense, return {"is_expense": false}.
- Return JSON only.
- ALWAYS return 'item' and 'category' in Simplified Chinese.
"""

def _run_ocr(image_path: str) -> str:
    import subprocess
    script_path = os.path.join(os.path.dirname(__file__), "ocr.swift")
    try:
        result = subprocess.run(
            ["swift", script_path, image_path],
            capture_output=True,
            text=True,
            check=True,
            timeout=20
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        print("OCR Error: timeout")
        return ""
    except subprocess.CalledProcessError as e:
        print(f"OCR Error: {e.stderr}")
        return ""

def parse_expense_image(image_path: str):
    # 1. Run OCR
    ocr_text = _run_ocr(image_path)
    if not ocr_text:
        return {"is_expense": False, "error": "OCR failed to extract text"}
    
    print(f"OCR Result:\n{ocr_text}\n---")
    # 2. First try deterministic heuristics tailored for receipts/bank transfers
    heur = _parse_receipt_heuristics(ocr_text)
    if heur:
        return heur
    # 3. Fallback to LLM parsing on cleaned text (avoid misleading time like 10:38)
    cleaned = _clean_ocr_for_llm(ocr_text)
    prompt_text = f"以下为小票/转账OCR文本，请提取金额、币种、类别与项目（中文）：\n{cleaned}"
    return parse_expense_text(prompt_text)

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

def _parse_receipt_heuristics(ocr_text: str):
    from datetime import datetime
    lines = [l.strip() for l in ocr_text.splitlines() if l.strip()]
    text_lower = ocr_text.lower()
    currency = None
    if any(k in text_lower for k in ["hk$", "hkd", "港币", "港元", "港幣"]):
        currency = "HKD"
    elif any(k in text_lower for k in ["cny", "rmb", "人民币", "¥", "￥", "元"]):
        currency = "CNY"
    keywords_total = ["total", "amount", "合计", "總計", "实付", "實付", "总额", "金額", "金額合計"]
    currency_tokens = ["HK$", "HKD", "CNY", "RMB", "¥", "￥"]
    candidates = []
    num_pattern = re.compile(r"[-]?\s*(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+\.\d{2})")
    for ln in lines:
        has_currency = any(tok in ln for tok in currency_tokens)
        has_total_kw = any(kw.lower() in ln.lower() for kw in keywords_total)
        is_negative_line = ln.strip().startswith("-")
        has_cny_word = ("元" in ln) or ("人民币" in ln) or ("人民幣" in ln)
        if has_currency or has_total_kw or is_negative_line or has_cny_word:
            for m in num_pattern.finditer(ln):
                val_str = m.group(1)
                try:
                    val = float(val_str.replace(",", ""))
                    candidates.append({
                        "amount": val,
                        "negative": ln.strip().startswith("-") or "-" in ln,
                        "currency": "HKD" if ("HK$" in ln or "HKD" in ln) else ("CNY" if ("CNY" in ln or "RMB" in ln or "¥" in ln or "￥" in ln or "元" in ln or "人民币" in ln) else currency),
                        "line": ln
                    })
                except:
                    pass
    chosen = None
    # Prefer monetary-looking decimals first
    decimals = [c for c in candidates if re.search(r"\d+\.\d{2}", c["line"])]
    neg_candidates = [c for c in decimals if c["negative"]] or [c for c in candidates if c["negative"]]
    if neg_candidates:
        chosen = max(neg_candidates, key=lambda c: c["amount"])
    elif decimals:
        total_candidates = [c for c in decimals if any(kw.lower() in c["line"].lower() for kw in keywords_total)]
        chosen = max(total_candidates or decimals, key=lambda c: c["amount"])
    elif candidates:
        # Prefer 'Total' lines first
        total_candidates = [c for c in candidates if any(kw.lower() in c["line"].lower() for kw in keywords_total)]
        chosen = max(total_candidates or candidates, key=lambda c: c["amount"])
    if not chosen:
        return None
    amount = chosen["amount"]
    cur = chosen["currency"] or currency or "CNY"
    # Parse date/time
    date_match = re.search(r"(20\d{2}[/-]\d{2}[/-]\d{2})", ocr_text)
    time_match = re.search(r"(\d{2}:\d{2}:\d{2})", ocr_text)
    dt_obj = None
    if date_match and time_match:
        dt_str = f"{date_match.group(1)} {time_match.group(1)}"
        for fmt in ["%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"]:
            try:
                dt_obj = datetime.strptime(dt_str, fmt)
                break
            except:
                continue
    elif date_match:
        for fmt in ["%Y/%m/%d", "%Y-%m-%d"]:
            try:
                dt_obj = datetime.strptime(date_match.group(1), fmt)
                break
            except:
                continue
    # Item/category summary
    item = "消费"
    category = "其他"
    bank_transfer_kw = ["转账", "轉賬", "轉账", "转數快", "轉數快", "FPS", "Faster Payment", "轉給", "转给"]
    payee_markers = ["收款人", "付款人", "Payee", "Beneficiary", "To"]
    merchant_hint = ["COFFEE", "STORE", "SHOP", "MART", "MARKET", "LIMITED", "7-11", "STARBUCKS", "WATSONS", "PARKnSHOP", "MCDONALD", "KFC"]
    if any(kw.lower() in text_lower for kw in [k.lower() for k in bank_transfer_kw]):
        name = None
        # 1) same line after transfer keywords
        for ln in lines:
            lnl = ln.lower()
            if any(kw.lower() in lnl for kw in bank_transfer_kw):
                # Chinese "转给XXX" pattern
                m_cn = re.search(r"(?:转给|轉給)\s*([^\s]{1,20})", ln)
                if m_cn:
                    cand = m_cn.group(1)
                    cand = re.sub(r"[#*]+", "", cand).strip()
                    if cand:
                        name = cand
                        break
                # English-like token fallback
                blocks = re.findall(r"[A-Za-z#][A-Za-z# ]{2,}", ln)
                if blocks:
                    cand = blocks[-1].strip()
                    cand = re.sub(r"\s{2,}", " ", cand)
                    if len(cand) >= 2 and not re.search(r"\d", cand):
                        name = cand
                        break
        # 2) payee markers
        if not name:
            for ln in lines:
                if any(pk.lower() in ln.lower() for pk in payee_markers):
                    # take trailing text as name
                    parts = re.split(r"[:：]", ln)
                    tail = parts[-1].strip()
                    tail = re.sub(r"\\s{2,}", " ", tail)
                    if tail and not re.search(r"\\d", tail):
                        name = tail
                        break
        # 3) fallback: pick a likely name-like uppercase line without digits
        if not name:
            for ln in lines:
                if len(ln) <= 2: 
                    continue
                if re.search(r"\\d", ln): 
                    continue
                if re.fullmatch(r"[A-Za-z# ]{3,}", ln):
                    name = re.sub(r"\\s{2,}", " ", ln).strip()
                    break
        category = "转账"
        item = f"转账给 {name}" if name else "转账"
    else:
        # merchant detection for receipts
        merch = None
        for ln in lines[:6]:  # top lines are more likely the merchant/header
            if any(h in ln.upper() for h in merchant_hint):
                if not re.search(r"\\d", ln):
                    merch = ln.strip()
                    break
        # 移除宽泛的英文大写回退，避免误识别噪声为商户
        if merch:
            item = f"在 {merch} 消费"
    # Return
    result = {"is_expense": True, "amount": amount, "currency": cur, "category": category, "item": item}
    if dt_obj:
        result["created_at"] = dt_obj
    return result

def _clean_ocr_for_llm(ocr_text: str):
    lines = []
    for ln in ocr_text.splitlines():
        s = ln.strip()
        if not s:
            continue
        # remove pure times and IDs
        if re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", s):
            continue
        if re.fullmatch(r"[A-Za-z0-9\\|-]{8,}", s.replace(" ", "")):
            continue
        lines.append(s)
    return "\n".join(lines)

def parse_expense_text(text: str):
    if not DEEPSEEK_API_KEY:
        fallback = _simple_parse(text)
        if fallback:
            return fallback
        return {"is_expense": False, "error": "NO_API_KEY"}

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text}
            ],
            response_format={ "type": "json_object" }
        )
        
        content = response.choices[0].message.content
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            fallback = _simple_parse(text)
            if fallback:
                return fallback
            return {"is_expense": False}
        if not parsed.get("is_expense"):
            fallback = _simple_parse(text)
            if fallback:
                return fallback
        cur = parsed.get("currency")
        if cur not in ("CNY", "HKD"):
            fallback = _simple_parse(text)
            if fallback:
                parsed["currency"] = fallback["currency"]
        amt = parsed.get("amount")
        if amt is None:
            fallback = _simple_parse(text)
            if fallback:
                parsed["amount"] = fallback["amount"]
        if "item" not in parsed or not parsed["item"]:
            parsed["item"] = text.strip()
        return parsed
    except Exception as e:
        fallback = _simple_parse(text)
        if fallback:
            return fallback
        return {"is_expense": False, "error": str(e)}
