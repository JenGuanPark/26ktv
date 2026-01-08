# 📊 家庭双币记账本 (Family Ledger)

这是一个基于 FastAPI + React + AI 的家庭记账项目，支持人民币 (CNY) 和港币 (HKD) 双币种记录。

## ✨ 功能特点

- **Telegram 智能记账**: 直接在群里说 "买菜 200" 或 "Taxi 50 HKD"，AI 自动识别金额、币种和类别。
- **双币种账本**: 独立记录 CNY 和 HKD 支出，互不干扰。
- **可视化看板**: 网页端实时展示支出统计、分类饼图和明细列表。

## 🚀 快速开始

### 1. 后端 (Backend)

确保你安装了 Python 3.8+。

```bash
cd backend

# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境变量
# 打开 .env 文件，填入你的 DeepSeek API Key 和 Telegram Bot Token
# DEEPSEEK_API_KEY=sk-xxxx
# TELEGRAM_BOT_TOKEN=123456:ABC-xxxx

# 3. 启动服务 (同时启动 API 和 Bot)
uvicorn app.main:app --reload
```

后端启动后：
- API 地址: `http://localhost:8000`
- Telegram Bot: 会自动开始监听消息

### 2. 前端 (Frontend)

确保你安装了 Node.js。

```bash
cd frontend

# 1. 安装依赖
npm install

# 2. 启动开发服务器
npm run dev
```

前端启动后，打开浏览器访问控制台显示的地址 (通常是 `http://localhost:5173`)。

## 🤖 使用指南

1. **Telegram Bot**:
   - 将你的 Bot 拉入家庭群组。
   - 发送消息：
     - `超市买肉 150` -> 记为 150 CNY，类别：餐饮/食材
     - `交电费 500 HKD` -> 记为 500 HKD，类别：居住/水电
     - `打车去旺角 80` -> 如果上下文或习惯是 HKD，AI 可能会识别，建议显式带上币种，或者默认 CNY。

2. **网页看板**:
   - 可以在顶部切换 "人民币" 和 "港币" 标签页。
   - 查看本月总支出和分类构成。

## 🛠️ 技术栈

- **Backend**: FastAPI, SQLAlchemy, SQLite, OpenAI SDK (DeepSeek), Python-Telegram-Bot
- **Frontend**: React, Vite, Ant Design, Recharts, TailwindCSS
