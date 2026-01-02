# Smart Environment Monitoring & LINE Alert System
# 智慧環境監控與 LINE 告警服務

An IoT solution integrating ESP32 sensors with a FastAPI backend to deliver real-time environmental safety alerts via LINE.
本專案整合 ESP32 感測器與 FastAPI 後端，實現即時環境安全監測並透過 LINE 發送告警。

---

## 🛠 Features / 功能

- **Push Message (`POST /send`)**: Send message to a specific user. (發送訊息給指定用戶)
- **Broadcast (`POST /broadcast`)**: Send message to all followers. (發送訊息給所有好友)
- **Multicast (`POST /multicast`)**: Send message to multiple users. (發送訊息給多個用戶)
- **Webhook (`POST /webhook`)**: Handle incoming events from LINE. (接收 LINE 事件)

---

## 🚀 Installation Steps / 安裝步驟

### 1. Install Dependencies / 安裝依賴
```bash
pip install -r requirements.txt
2. 設定線路通道
前往LINE開發者控制台。

建立提供者和訊息傳遞 API 通道。

在「訊息傳遞 API」標籤中：

頒發通道存取令牌。

設定Webhook URL （您的伺服器 URL + /webhook）。

啟用使用 webhook 。

前往LINE開發者控制台。

建立 Provider 並建立 Messaging API Channel。

在 Messaging API 頁籤中：

取得Channel Access Token 。

設定 Webhook URL (部署網址 + /webhook)。

開啟 Use webhook。

3. Environment Configuration / 設定環境變數
We use .env to protect sensitive credentials. 我們使用 .env 檔案來保護敏感資訊。

```bash

# Copy template / 複製範例檔案
cp .env.example .env

# Edit .env and fill in your LINE_CHANNEL_ACCESS_TOKEN and other keys.
# 編輯 .env，填入您的 Token 與相關設定。
4. Start Service / 啟動服務
```bash

# Development mode with auto-reload / 開發模式
uvicorn main:app --reload --host 0.0.0.0 --port 8000
Access http://localhost:8000/docs to view Interactive API Documentation. 啟動後訪問 http://localhost:8000/docs 查看 API 文件。

💻 API Usage Examples / 使用範例
Push Message / 推播訊息
```bash

curl -X POST "http://localhost:8000/send" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "U1234567890abcdef",
    "message": "Hazard Alert: Gas Leak Detected!"
  }'
Broadcast / 廣播訊息
```bash

curl -X POST "http://localhost:8000/broadcast" \
  -H "Content-Type: application/json" \
  -d '{ "message": "This is a broadcast message!" }'
📡 Local Testing (ngrok) / 本地測試
To receive Webhooks on your local machine, use ngrok: 若要在本機接收 Webhook，建議使用 ngrok：

```bash

ngrok http 8000
# Update the generated HTTPS URL to your LINE Developer Console Webhook setting.
# 將產生的 HTTPS 網址設定為 LINE 後台的 Webhook URL。
⚠️ Notes / 注意事項
Quotas: Push and Multicast messages have limits on free plans. (免費方案的推播次數有限制)

Reply Tokens: These are free but valid only for a short period. (回覆訊息免費但時效極短)

Security: Never commit your .env file to GitHub. (切勿將 .env 上傳至 GitHub)