"""
ESP32 IoT 環境監控系統 - FastAPI 後端
功能：
1. MQTT 訂閱感測器資料
2. SQLite 資料庫存儲
3. REST API 提供歷史資料查詢
"""

import asyncio
import json
import ssl
import sqlite3
import os
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from typing import Optional
import threading

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import paho.mqtt.client as mqtt

# ==================== 環境變數設定 ====================
# 手動從 .env 文件讀取配置（無需依賴 python-dotenv 套件）

def load_config_from_env():
    """從本地 .env 文件讀取配置"""
    config = {}
    try:
        with open('.env', 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    if '=' in line:
                        key, value = line.split('=', 1)
                        config[key.strip()] = value.strip().strip('"\'')
    except FileNotFoundError:
        print("⚠️  未找到 .env 文件，使用預設值")
    except Exception as e:
        print(f"⚠️  讀取 .env 文件失敗: {e}，使用預設值")
    return config

_config = load_config_from_env()

def get_config(key, default=None):
    """安全地獲取配置值"""
    return _config.get(key, default)

# ==================== 配置 ====================

# MQTT 設定 - 從環境變數讀取

MQTT_BROKER = get_config("MQTT_BROKER", "8be4a35a58084bec968d67f734dc2454.s1.eu.hivemq.cloud")
MQTT_PORT = int(get_config("MQTT_PORT", 8883))
MQTT_USER = get_config("MQTT_USER", "shawnc20")
MQTT_PASSWORD = get_config("MQTT_PASSWORD", "Shawnc20")

# MQTT Topics
TOPIC_GAS_DATA = "sensor/gas/data"
TOPIC_TEMP_DATA = "sensor/temp/data"
TOPIC_ALARM_LOG = "sensor/alarm/log"

# 資料庫路徑
DB_PATH = "sensor_data.db"

# ==================== 資料庫初始化 ====================

def init_database():
    """初始化 SQLite 資料庫"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 氣體感測器資料表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gas_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            raw_value INTEGER NOT NULL,
            voltage REAL NOT NULL,
            percentage REAL NOT NULL,
            threshold INTEGER NOT NULL,
            alarm BOOLEAN NOT NULL,
            buzzer_enabled BOOLEAN NOT NULL,
            manual_silence BOOLEAN NOT NULL,
            timestamp REAL NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 溫濕度感測器資料表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS temp_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            temperature REAL NOT NULL,
            humidity REAL NOT NULL,
            temp_threshold REAL NOT NULL,
            alarm BOOLEAN NOT NULL,
            valid BOOLEAN NOT NULL,
            timestamp REAL NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 警報日誌資料表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alarm_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alarm_type TEXT NOT NULL,
            message TEXT NOT NULL,
            timestamp REAL NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 建立索引加速查詢
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_gas_created_at ON gas_readings(created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_temp_created_at ON temp_readings(created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_alarm_created_at ON alarm_logs(created_at)")
    
    conn.commit()
    conn.close()
    print("✓ 資料庫初始化完成")


def save_gas_reading(data: dict):
    """儲存氣體感測資料"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO gas_readings 
            (raw_value, voltage, percentage, threshold, alarm, buzzer_enabled, manual_silence, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.get("raw", 0),
            data.get("voltage", 0),
            data.get("percentage", 0),
            data.get("threshold", 1500),
            data.get("alarm", False),
            data.get("buzzer_enabled", True),
            data.get("manual_silence", False),
            data.get("timestamp", datetime.now().timestamp())
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"儲存氣體資料失敗: {e}")


def save_temp_reading(data: dict):
    """儲存溫濕度感測資料"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO temp_readings 
            (temperature, humidity, temp_threshold, alarm, valid, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            data.get("temperature", 0),
            data.get("humidity", 0),
            data.get("temp_threshold", 35),
            data.get("alarm", False),
            data.get("valid", True),
            data.get("timestamp", datetime.now().timestamp())
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"儲存溫濕度資料失敗: {e}")


def save_alarm_log(data: dict):
    """儲存警報日誌"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO alarm_logs (alarm_type, message, timestamp)
            VALUES (?, ?, ?)
        """, (
            data.get("type", "unknown"),
            data.get("message", ""),
            data.get("timestamp", datetime.now().timestamp())
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"儲存警報日誌失敗: {e}")


# ==================== MQTT 客戶端 ====================

mqtt_client = None

def on_connect(client, userdata, flags, rc, properties=None):
    """MQTT 連線回調"""
    if rc == 0:
        print("✓ MQTT 連線成功!")
        client.subscribe(TOPIC_GAS_DATA)
        client.subscribe(TOPIC_TEMP_DATA)
        client.subscribe(TOPIC_ALARM_LOG)
        print(f"  已訂閱: {TOPIC_GAS_DATA}, {TOPIC_TEMP_DATA}, {TOPIC_ALARM_LOG}")
    else:
        print(f"✗ MQTT 連線失敗，代碼: {rc}")


def on_message(client, userdata, msg):
    """MQTT 訊息回調"""
    try:
        topic = msg.topic
        payload = json.loads(msg.payload.decode())
        
        if topic == TOPIC_GAS_DATA:
            save_gas_reading(payload)
            print(f"[GAS] Raw: {payload.get('raw')} | Alarm: {payload.get('alarm')}")
            
        elif topic == TOPIC_TEMP_DATA:
            save_temp_reading(payload)
            print(f"[TEMP] {payload.get('temperature')}°C | Humidity: {payload.get('humidity')}%")
            
        elif topic == TOPIC_ALARM_LOG:
            save_alarm_log(payload)
            print(f"[ALARM] {payload.get('type')}: {payload.get('message')}")
            
    except Exception as e:
        print(f"處理 MQTT 訊息失敗: {e}")


def start_mqtt_client():
    """啟動 MQTT 客戶端"""
    global mqtt_client
    
    mqtt_client = mqtt.Client(
        client_id="fastapi_server",
        protocol=mqtt.MQTTv5
    )
    
    mqtt_client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
    mqtt_client.tls_set(tls_version=ssl.PROTOCOL_TLS)
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message
    
    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_start()
        print("✓ MQTT 客戶端已啟動")
    except Exception as e:
        print(f"✗ MQTT 連線失敗: {e}")


def stop_mqtt_client():
    """停止 MQTT 客戶端"""
    global mqtt_client
    if mqtt_client:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        print("✓ MQTT 客戶端已停止")


# ==================== FastAPI 應用 ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """應用生命週期管理"""
    # 啟動時
    init_database()
    start_mqtt_client()
    yield
    # 關閉時
    stop_mqtt_client()


app = FastAPI(
    title="ESP32 環境監控 API",
    description="提供感測器歷史資料查詢",
    version="1.0.0",
    lifespan=lifespan
)

# CORS 設定（允許前端跨域請求）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== API 端點 ====================

@app.get("/")
async def root():
    """API 根路徑"""
    return {
        "message": "ESP32 環境監控 API",
        "endpoints": {
            "氣體資料": "/api/gas",
            "溫濕度資料": "/api/temperature",
            "警報日誌": "/api/alarms",
            "統計資料": "/api/stats"
        }
    }


@app.get("/api/gas")
async def get_gas_readings(
    start_date: Optional[str] = Query(None, description="開始日期 (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="結束日期 (YYYY-MM-DD)"),
    limit: int = Query(100, ge=1, le=10000, description="最大筆數")
):
    """
    取得氣體感測器歷史資料
    
    - **start_date**: 開始日期（格式：YYYY-MM-DD）
    - **end_date**: 結束日期（格式：YYYY-MM-DD）
    - **limit**: 最大回傳筆數（預設 100，最大 10000）
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        query = "SELECT * FROM gas_readings WHERE 1=1"
        params = []
        
        if start_date:
            query += " AND DATE(created_at) >= ?"
            params.append(start_date)
        
        if end_date:
            query += " AND DATE(created_at) <= ?"
            params.append(end_date)
        
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        return {
            "count": len(rows),
            "data": [dict(row) for row in rows]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/temperature")
async def get_temp_readings(
    start_date: Optional[str] = Query(None, description="開始日期 (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="結束日期 (YYYY-MM-DD)"),
    limit: int = Query(100, ge=1, le=10000, description="最大筆數")
):
    """
    取得溫濕度感測器歷史資料
    
    - **start_date**: 開始日期（格式：YYYY-MM-DD）
    - **end_date**: 結束日期（格式：YYYY-MM-DD）
    - **limit**: 最大回傳筆數（預設 100，最大 10000）
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        query = "SELECT * FROM temp_readings WHERE 1=1"
        params = []
        
        if start_date:
            query += " AND DATE(created_at) >= ?"
            params.append(start_date)
        
        if end_date:
            query += " AND DATE(created_at) <= ?"
            params.append(end_date)
        
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        return {
            "count": len(rows),
            "data": [dict(row) for row in rows]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/alarms")
async def get_alarm_logs(
    start_date: Optional[str] = Query(None, description="開始日期 (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="結束日期 (YYYY-MM-DD)"),
    alarm_type: Optional[str] = Query(None, description="警報類型 (gas/temp/gas_clear/temp_clear)"),
    limit: int = Query(100, ge=1, le=10000, description="最大筆數")
):
    """
    取得警報日誌
    
    - **start_date**: 開始日期（格式：YYYY-MM-DD）
    - **end_date**: 結束日期（格式：YYYY-MM-DD）
    - **alarm_type**: 警報類型篩選
    - **limit**: 最大回傳筆數（預設 100，最大 10000）
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        query = "SELECT * FROM alarm_logs WHERE 1=1"
        params = []
        
        if start_date:
            query += " AND DATE(created_at) >= ?"
            params.append(start_date)
        
        if end_date:
            query += " AND DATE(created_at) <= ?"
            params.append(end_date)
        
        if alarm_type:
            query += " AND alarm_type = ?"
            params.append(alarm_type)
        
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        return {
            "count": len(rows),
            "data": [dict(row) for row in rows]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats")
async def get_statistics(
    start_date: Optional[str] = Query(None, description="開始日期 (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="結束日期 (YYYY-MM-DD)")
):
    """
    取得統計資料
    
    - **start_date**: 開始日期（格式：YYYY-MM-DD）
    - **end_date**: 結束日期（格式：YYYY-MM-DD）
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # 建構日期條件
        date_condition = ""
        params = []
        
        if start_date:
            date_condition += " AND DATE(created_at) >= ?"
            params.append(start_date)
        
        if end_date:
            date_condition += " AND DATE(created_at) <= ?"
            params.append(end_date)
        
        # 氣體統計
        cursor.execute(f"""
            SELECT 
                COUNT(*) as total_readings,
                AVG(raw_value) as avg_value,
                MAX(raw_value) as max_value,
                MIN(raw_value) as min_value,
                SUM(CASE WHEN alarm = 1 THEN 1 ELSE 0 END) as alarm_count
            FROM gas_readings
            WHERE 1=1 {date_condition}
        """, params)
        gas_stats = cursor.fetchone()
        
        # 溫度統計
        cursor.execute(f"""
            SELECT 
                COUNT(*) as total_readings,
                AVG(temperature) as avg_temp,
                MAX(temperature) as max_temp,
                MIN(temperature) as min_temp,
                AVG(humidity) as avg_humidity,
                MAX(humidity) as max_humidity,
                MIN(humidity) as min_humidity,
                SUM(CASE WHEN alarm = 1 THEN 1 ELSE 0 END) as alarm_count
            FROM temp_readings
            WHERE 1=1 {date_condition}
        """, params)
        temp_stats = cursor.fetchone()
        
        # 警報統計
        cursor.execute(f"""
            SELECT alarm_type, COUNT(*) as count
            FROM alarm_logs
            WHERE 1=1 {date_condition}
            GROUP BY alarm_type
        """, params)
        alarm_stats = cursor.fetchall()
        
        conn.close()
        
        return {
            "gas": {
                "total_readings": gas_stats[0] or 0,
                "avg_value": round(gas_stats[1], 2) if gas_stats[1] else 0,
                "max_value": gas_stats[2] or 0,
                "min_value": gas_stats[3] or 0,
                "alarm_count": gas_stats[4] or 0
            },
            "temperature": {
                "total_readings": temp_stats[0] or 0,
                "avg_temp": round(temp_stats[1], 1) if temp_stats[1] else 0,
                "max_temp": temp_stats[2] or 0,
                "min_temp": temp_stats[3] or 0,
                "avg_humidity": round(temp_stats[4], 1) if temp_stats[4] else 0,
                "max_humidity": temp_stats[5] or 0,
                "min_humidity": temp_stats[6] or 0,
                "alarm_count": temp_stats[7] or 0
            },
            "alarms": {row[0]: row[1] for row in alarm_stats}
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/chart-data")
async def get_chart_data(
    hours: int = Query(24, ge=1, le=168, description="過去幾小時的資料"),
    interval: int = Query(5, ge=1, le=60, description="資料間隔（分鐘）")
):
    """
    取得圖表用資料（聚合資料）
    
    - **hours**: 過去幾小時（預設 24，最大 168）
    - **interval**: 資料聚合間隔，分鐘（預設 5，最大 60）
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # 計算時間範圍
        now = datetime.now()
        start_time = now - timedelta(hours=hours)
        
        # 氣體資料（按時間區間聚合）
        cursor.execute("""
            SELECT 
                strftime('%Y-%m-%d %H:', created_at) || 
                    printf('%02d', (CAST(strftime('%M', created_at) AS INTEGER) / ?) * ?) || ':00' as time_bucket,
                AVG(raw_value) as avg_value,
                MAX(raw_value) as max_value,
                MIN(raw_value) as min_value
            FROM gas_readings
            WHERE created_at >= ?
            GROUP BY time_bucket
            ORDER BY time_bucket
        """, (interval, interval, start_time.strftime('%Y-%m-%d %H:%M:%S')))
        gas_data = [{"time": row[0], "avg": round(row[1], 1), "max": row[2], "min": row[3]} 
                    for row in cursor.fetchall()]
        
        # 溫度資料
        cursor.execute("""
            SELECT 
                strftime('%Y-%m-%d %H:', created_at) || 
                    printf('%02d', (CAST(strftime('%M', created_at) AS INTEGER) / ?) * ?) || ':00' as time_bucket,
                AVG(temperature) as avg_temp,
                MAX(temperature) as max_temp,
                MIN(temperature) as min_temp,
                AVG(humidity) as avg_humidity
            FROM temp_readings
            WHERE created_at >= ?
            GROUP BY time_bucket
            ORDER BY time_bucket
        """, (interval, interval, start_time.strftime('%Y-%m-%d %H:%M:%S')))
        temp_data = [{"time": row[0], "avg_temp": round(row[1], 1), "max_temp": row[2], 
                      "min_temp": row[3], "avg_humidity": round(row[4], 1)} 
                     for row in cursor.fetchall()]
        
        conn.close()
        
        return {
            "gas": gas_data,
            "temperature": temp_data,
            "period": {
                "start": start_time.isoformat(),
                "end": now.isoformat(),
                "hours": hours,
                "interval_minutes": interval
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 靜態檔案服務 ====================

# 提供 index.html
@app.get("/dashboard")
async def serve_dashboard():
    """提供儀表板頁面"""
    return FileResponse("index.html")


# ==================== 主程式入口 ====================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)