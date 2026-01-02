from machine import Pin, ADC, PWM
import time
import network
import ssl
from umqtt.simple import MQTTClient
import json
import dht
import urequests  # For HTTP requests
import os

# ==================== 環境變數設定 ====================

# 注意：MicroPython 不支持 python-dotenv
# 請在本地開發時使用 .env 文件，或在 ESP32 中直接配置這些值
# 臨時解決方案：從文件讀取配置

def load_config_from_env():
    """從本地 .env 文件讀取配置（開發用）"""
    config = {}
    try:
        with open('.env', 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    key, value = line.split('=', 1)
                    config[key.strip()] = value.strip()
    except:
        print("⚠️  無法讀取 .env 文件，使用預設值")
    return config

_config = load_config_from_env()

def get_config(key, default=None):
    """安全地獲取配置值"""
    return _config.get(key, default)

# ==================== Configuration ====================

# WiFi Settings - 從環境變數讀取
WIFI_SSID = get_config("WIFI_SSID", "Shawn iPhone")
WIFI_PASSWORD = get_config("WIFI_PASSWORD", "0918959582")

# MQTT Settings - 從環境變數讀取
MQTT_BROKER = get_config("MQTT_BROKER", "8be4a35a58084bec968d67f734dc2454.s1.eu.hivemq.cloud")
MQTT_PORT = int(get_config("MQTT_PORT", 8883))
MQTT_USER = get_config("MQTT_USER", "shawnc20")
MQTT_PASSWORD = get_config("MQTT_PASSWORD", "Shawnc20")
MQTT_CLIENT_ID = "esp32_gas_sensor"

# MQTT Topics
TOPIC_GAS_DATA = b"sensor/gas/data"           # Publish gas data
TOPIC_TEMP_DATA = b"sensor/temp/data"         # Publish temperature & humidity
TOPIC_BUZZER_CONTROL = b"sensor/gas/buzzer"   # Subscribe buzzer control
TOPIC_ALARM_LOG = b"sensor/alarm/log"         # Publish alarm logs

# FastAPI Line Settings - 從環境變數讀取
FASTAPI_URL = get_config("FASTAPI_URL", "https://unapportioned-palmira-platyhelminthic.ngrok-free.dev")
LINE_USER_ID = get_config("LINE_USER_ID", "your_line_user_id")

# Hardware Pin Configuration
GAS_SENSOR_PIN = 34    # MQ-2 analog output (AO)
DHT_PIN = 4            # DHT data pin
BUZZER_PIN = 25        # Buzzer pin

# DHT Sensor Type (choose one)
DHT_TYPE = "DHT11"
# DHT_TYPE = "DHT22"

# Alarm Thresholds
GAS_THRESHOLD = 1500       # Gas threshold (ADC raw value 0-4095)
TEMP_THRESHOLD = 35.0      # Temperature upper limit (C)
HYSTERESIS = 100           # Gas hysteresis
TEMP_HYSTERESIS = 1.0      # Temperature hysteresis (C)

# ==================== Global Variables ====================

buzzer_enabled = True
gas_alarm_active = False
temp_alarm_active = False
manual_silence = False
client = None

current_temp = 0.0
current_humidity = 0.0

# Prevent duplicate Line notifications
gas_line_notified = False
temp_line_notified = False

# ==================== Hardware Initialization ====================

# MQ-2 ADC Configuration
adc = ADC(Pin(GAS_SENSOR_PIN))
adc.atten(ADC.ATTN_11DB)
adc.width(ADC.WIDTH_12BIT)

# DHT Sensor Setup
if DHT_TYPE == "DHT11":
    dht_sensor = dht.DHT11(Pin(DHT_PIN))
else:
    dht_sensor = dht.DHT22(Pin(DHT_PIN))

# Buzzer (PWM)
buzzer = PWM(Pin(BUZZER_PIN), freq=1000, duty=0)

# ==================== Functions ====================

def connect_wifi():
    """Connect to WiFi"""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if not wlan.isconnected():
        print(f"Connecting to WiFi: {WIFI_SSID}...")
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)

        timeout = 20
        while not wlan.isconnected() and timeout > 0:
            time.sleep(1)
            timeout -= 1
            print(".", end="")

        print()

    if wlan.isconnected():
        print(f"WiFi connected! IP: {wlan.ifconfig()[0]}")
        return True
    else:
        print("WiFi connection failed!")
        return False


def http_post_with_ssl(url, payload):
    """
    Send HTTP POST request with SSL support for HTTPS URLs
    Handles SSL connection issues on ESP32
    """
    import socket
    
    # Parse URL
    if url.startswith("https://"):
        use_ssl = True
        url = url[8:]
        port = 443
    elif url.startswith("http://"):
        use_ssl = False
        url = url[7:]
        port = 80
    else:
        raise ValueError("URL must start with http:// or https://")
    
    # Split host and path
    if "/" in url:
        host, path = url.split("/", 1)
        path = "/" + path
    else:
        host = url
        path = "/"
    
    # Check for custom port
    if ":" in host:
        host, port_str = host.split(":")
        port = int(port_str)
    
    # Convert payload to JSON
    body = json.dumps(payload)
    
    # Build HTTP request
    request = (
        f"POST {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Connection: close\r\n"
        f"\r\n"
        f"{body}"
    )
    
    try:
        # Create socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        
        # Resolve hostname
        addr = socket.getaddrinfo(host, port)[0][-1]
        sock.connect(addr)
        
        # Wrap with SSL if needed
        if use_ssl:
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ssl_context.verify_mode = ssl.CERT_NONE
            sock = ssl_context.wrap_socket(sock, server_hostname=host)
        
        # Send request
        sock.write(request.encode())
        
        # Read response
        response = b""
        while True:
            try:
                chunk = sock.read(1024)
                if not chunk:
                    break
                response += chunk
            except:
                break
        
        sock.close()
        
        # Parse response
        response_str = response.decode()
        
        # Get status code
        status_line = response_str.split("\r\n")[0]
        status_code = int(status_line.split(" ")[1])
        
        # Get body (after double CRLF)
        if "\r\n\r\n" in response_str:
            body = response_str.split("\r\n\r\n", 1)[1]
        else:
            body = ""
        
        return status_code, body
        
    except Exception as e:
        print(f"HTTP request error: {e}")
        return None, str(e)


def send_line_notification(message):
    """
    Send Line notification to FastAPI server
    Uses /send endpoint to push message to specific user
    """
    url = f"{FASTAPI_URL}/send"
    
    payload = {
        "user_id": LINE_USER_ID,
        "message": message
    }
    
    try:
        print(f"Sending Line notification...")
        status_code, response_body = http_post_with_ssl(url, payload)
        
        if status_code == 200:
            print("+ Line notification sent successfully!")
            return True
        else:
            print(f"x Line notification failed! Status: {status_code}")
            print(f"  Error: {response_body}")
            return False
        
    except Exception as e:
        print(f"x Error sending Line notification: {e}")
        return False


def send_line_broadcast(message):

    print('here')
    """
    Broadcast Line notification to all friends
    Uses /broadcast endpoint
    """
    url = f"{FASTAPI_URL}/broadcast"
    
    payload = {
        "message": message
    }
    
    try:
        print(f"Broadcasting Line notification...")
        status_code, response_body = http_post_with_ssl(url, payload)
        
        if status_code == 200:
            print("+ Line broadcast sent successfully!")
            return True
        else:
            print(f"x Line broadcast failed! Status: {status_code}")
            print(f"  Error: {response_body}")
            return False
        
    except Exception as e:
        print(f"x Error broadcasting Line notification: {e}")
        return False


def mqtt_callback(topic, msg):
    """MQTT message callback"""
    global buzzer_enabled, manual_silence, TEMP_THRESHOLD, GAS_THRESHOLD

    print(f"MQTT message received - Topic: {topic}, Message: {msg}")

    try:
        data = json.loads(msg)

        if data.get("command") == "silence":
            manual_silence = True
            buzzer_off()
            print("Silence command received, buzzer muted")

        elif data.get("command") == "enable":
            buzzer_enabled = True
            manual_silence = False
            print("Buzzer enabled")

        elif data.get("command") == "disable":
            buzzer_enabled = False
            buzzer_off()
            print("Buzzer disabled")

        elif data.get("command") == "reset":
            manual_silence = False
            print("Alarm state reset")

        elif data.get("command") == "set_temp_threshold":
            value = data.get("value")
            if value is not None:
                TEMP_THRESHOLD = float(value)
                print(f"Temperature threshold updated: {TEMP_THRESHOLD}C")

        elif data.get("command") == "set_gas_threshold":
            value = data.get("value")
            if value is not None:
                GAS_THRESHOLD = int(value)
                print(f"Gas threshold updated: {GAS_THRESHOLD}")

    except Exception as e:
        print(f"Error processing MQTT message: {e}")


def connect_mqtt():
    """Connect to MQTT Broker (TLS)"""
    global client

    print(f"Connecting to MQTT Broker: {MQTT_BROKER}...")

    try:
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_context.verify_mode = ssl.CERT_NONE

        client = MQTTClient(
            client_id=MQTT_CLIENT_ID,
            server=MQTT_BROKER,
            port=MQTT_PORT,
            user=MQTT_USER,
            password=MQTT_PASSWORD,
            ssl=ssl_context,
            keepalive=60
        )

        client.set_callback(mqtt_callback)
        client.connect()
        client.subscribe(TOPIC_BUZZER_CONTROL)

        print(f"Subscribed to topic: {TOPIC_BUZZER_CONTROL}")
        print("MQTT connected successfully!")
        return True

    except Exception as e:
        print(f"MQTT connection failed: {e}")
        return False


def buzzer_on():
    """Turn buzzer ON"""
    buzzer.duty(512)


def buzzer_off():
    """Turn buzzer OFF"""
    buzzer.duty(0)


def read_gas_sensor():
    """Read MQ-2 gas sensor"""
    samples = []
    for _ in range(10):
        samples.append(adc.read())
        time.sleep_ms(10)

    raw = sum(samples) // len(samples)
    voltage = raw / 4095 * 3.3
    percentage = (raw / 4095) * 100

    return {
        "raw": raw,
        "voltage": round(voltage, 2),
        "percentage": round(percentage, 1)
    }


def read_dht_sensor():
    """Read DHT temperature and humidity"""
    global current_temp, current_humidity

    try:
        dht_sensor.measure()
        current_temp = dht_sensor.temperature()
        current_humidity = dht_sensor.humidity()
        return {
            "temperature": current_temp,
            "humidity": current_humidity,
            "valid": True
        }
    except Exception as e:
        print(f"DHT read failed: {e}")
        return {
            "temperature": current_temp,
            "humidity": current_humidity,
            "valid": False
        }


def publish_alarm_log(alarm_type, message):
    """Publish alarm log"""
    payload = {
        "type": alarm_type,
        "message": message,
        "timestamp": time.time()
    }

    try:
        client.publish(TOPIC_ALARM_LOG, json.dumps(payload))
        print(f"Alarm log published: {alarm_type} - {message}")
    except Exception as e:
        print(f"Failed to publish alarm log: {e}")


def check_gas_alarm(value):
    """Check gas alarm and send Line notification"""
    global gas_alarm_active, manual_silence, gas_line_notified

    if value >= GAS_THRESHOLD:
        if not gas_alarm_active:
            gas_alarm_active = True
            manual_silence = False
            print("!!! GAS ALARM TRIGGERED !!!")
            
            # Publish MQTT alarm log
            publish_alarm_log(
                "gas",
                f"Gas concentration exceeded threshold! Value: {value}, Threshold: {GAS_THRESHOLD}"
            )
            
            # Send Line notification (only once)
            if not gas_line_notified:
                message = (
                    f"GAS ALERT!\n"
                    f"==============\n"
                    f"Gas level exceeded!\n"
                    f"Current: {value}\n"
                    f"Threshold: {GAS_THRESHOLD}\n"
                    f"Temp: {current_temp}C\n"
                    f"Humidity: {current_humidity}%\n"
                    f"==============\n"
                    f"Check environment immediately!"
                )
                if send_line_broadcast(message):
                    gas_line_notified = True

    elif value < (GAS_THRESHOLD - HYSTERESIS):
        if gas_alarm_active:
            gas_alarm_active = False
            gas_line_notified = False  # Reset notification status
            print("+ Gas level back to normal")
            publish_alarm_log("gas_clear", f"Gas level normal. Value: {value}")
            
            # Send alarm cleared notification
            message = (
                f"GAS ALERT CLEARED\n"
                f"==============\n"
                f"Gas level is normal\n"
                f"Current: {value}\n"
                f"Threshold: {GAS_THRESHOLD}"
            )
            send_line_broadcast(message)


def check_temp_alarm(value):
    """Check temperature alarm and send Line notification"""
    global temp_alarm_active, manual_silence, temp_line_notified

    if value >= TEMP_THRESHOLD:
        if not temp_alarm_active:
            temp_alarm_active = True
            manual_silence = False
            print("!!! TEMPERATURE ALARM TRIGGERED !!!")
            
            # Publish MQTT alarm log
            publish_alarm_log(
                "temp",
                f"Temperature exceeded threshold! Value: {value}C, Threshold: {TEMP_THRESHOLD}C"
            )
            
            # Send Line notification (only once)
            if not temp_line_notified:
                message = (
                    f"HIGH TEMP ALERT!\n"
                    f"==============\n"
                    f"Temperature too high!\n"
                    f"Current: {value}C\n"
                    f"Threshold: {TEMP_THRESHOLD}C\n"
                    f"Humidity: {current_humidity}%\n"
                    f"==============\n"
                    f"Check environment!"
                )
                if send_line_broadcast(message):
                    temp_line_notified = True

    elif value < (TEMP_THRESHOLD - TEMP_HYSTERESIS):
        if temp_alarm_active:
            temp_alarm_active = False
            temp_line_notified = False  # Reset notification status
            print("+ Temperature back to normal")
            publish_alarm_log("temp_clear", f"Temperature normal. Value: {value}C")
            
            # Send alarm cleared notification
            message = (
                f"TEMP ALERT CLEARED\n"
                f"==============\n"
                f"Temperature is normal\n"
                f"Current: {value}C\n"
                f"Threshold: {TEMP_THRESHOLD}C"
            )
            send_line_broadcast(message)


def update_buzzer():
    """Update buzzer state"""
    alarm_triggered = gas_alarm_active or temp_alarm_active

    if alarm_triggered and buzzer_enabled and not manual_silence:
        buzzer_on()
    else:
        buzzer_off()


def publish_gas_data(data):
    """Publish gas data"""
    payload = {
        "raw": data["raw"],
        "voltage": data["voltage"],
        "percentage": data["percentage"],
        "threshold": GAS_THRESHOLD,
        "alarm": gas_alarm_active,
        "buzzer_enabled": buzzer_enabled,
        "manual_silence": manual_silence,
        "timestamp": time.time()
    }

    try:
        client.publish(TOPIC_GAS_DATA, json.dumps(payload))
    except Exception as e:
        print(f"Failed to publish gas data: {e}")


def publish_temp_data(data):
    """Publish temperature & humidity"""
    payload = {
        "temperature": data["temperature"],
        "humidity": data["humidity"],
        "temp_threshold": TEMP_THRESHOLD,
        "alarm": temp_alarm_active,
        "valid": data["valid"],
        "timestamp": time.time()
    }

    try:
        client.publish(TOPIC_TEMP_DATA, json.dumps(payload))
    except Exception as e:
        print(f"Failed to publish temperature data: {e}")


def test_line_connection():
    """Test Line API connection"""
    print("\nTesting Line API connection...")
    message = (
        f"ESP32 Monitor Started\n"
        f"==============\n"
        f"System online!\n"
        f"Gas threshold: {GAS_THRESHOLD}\n"
        f"Temp threshold: {TEMP_THRESHOLD}C\n"
        f"==============\n"
        f"Monitoring..."
    )
    
    if send_line_broadcast(message):
        print("+ Line API connection test successful!")
        return True
    else:
        print("x Line API connection test failed, check settings")
        return False


# ==================== Main Program ====================

def main():
    print("\n" + "=" * 50)
    print("ESP32 Environmental Monitoring System")
    print("MQ-2 Gas Sensor + DHT Temperature & Humidity")
    print("With Line Notification Support")
    print("=" * 50 + "\n")

    if not connect_wifi():
        print("WiFi connection failed. Program stopped.")
        return

    if not connect_mqtt():
        print("MQTT connection failed. Program stopped.")
        return

    # Test Line API connection and send startup notification
    test_line_connection()

    print("\nWarming up MQ-2 sensor, please wait 20 seconds...")
    for i in range(20, 0, -1):
        print(f"\rWarm-up countdown: {i}s", end="")
        time.sleep(1)

    print("\nWarm-up completed. Monitoring started...\n")

    last_publish = 0
    last_dht_read = 0

    while True:
        try:
            client.check_msg()
            now = time.time()

            gas_data = read_gas_sensor()
            check_gas_alarm(gas_data["raw"])

            if now - last_dht_read >= 2:
                temp_data = read_dht_sensor()
                last_dht_read = now
                if temp_data["valid"]:
                    check_temp_alarm(temp_data["temperature"])

            update_buzzer()

            if now - last_publish >= 2:
                publish_gas_data(gas_data)
                publish_temp_data({
                    "temperature": current_temp,
                    "humidity": current_humidity,
                    "valid": True
                })
                last_publish = now

                gas_status = "!GAS!" if gas_alarm_active else "OK"
                temp_status = "!TEMP!" if temp_alarm_active else "OK"

                print(f"[{gas_status}] Gas: {gas_data['raw']} | "
                      f"[{temp_status}] Temp: {current_temp}C | "
                      f"Humidity: {current_humidity}%")

            time.sleep_ms(100)

        except KeyboardInterrupt:
            print("\nProgram interrupted")
            break

        except Exception as e:
            print(f"Error occurred: {e}")
            time.sleep(5)
            try:
                connect_mqtt()
            except:
                pass

    buzzer_off()
    if client:
        client.disconnect()
    print("Program terminated")


if __name__ == "__main__":
    main()