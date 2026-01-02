# 環境配置指南

## 敏感信息安全設置

本項目包含敏感信息（密碼、API密鑰等），已配置為使用環境變數管理。

### 🔧 設置步驟

1. **複製環境變數模板**
   ```bash
   cp .env.example .env
   ```

2. **編輯 `.env` 文件**
   使用文本編輯器打開 `.env`，填入你的實際配置：
   ```
   MQTT_USER=你的_MQTT_用戶名
   MQTT_PASSWORD=你的_MQTT_密碼
   WIFI_SSID=你的_WiFi_名稱
   WIFI_PASSWORD=你的_WiFi_密碼
   LINE_USER_ID=你的_Line_User_ID
   ```

3. **確保 `.gitignore` 工作正常**
   - `.env` 文件永遠不會被提交到 GitHub
   - 只有 `.env.example` 會被版本控制

### ⚠️ 重要提醒

- **不要將 `.env` 提交到版本控制**
- **不要分享你的 `.env` 文件**
- 在本地開發時使用 `.env`
- 在線上服務器使用環境變數或密鑰管理工具

### 📋 安全檢查清單

- [ ] 創建 `.env` 文件
- [ ] 填入所有敏感信息
- [ ] 驗證 `.env` 在 `.gitignore` 中
- [ ] 運行 `git status` 確認 `.env` 不會被追蹤
- [ ] 提交代碼前再次檢查
