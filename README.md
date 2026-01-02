# Smart Environment Monitoring & Safety System

## Project Overview
This project is an **integrated IoT solution** designed for real-time environmental safety monitoring. By connecting an **ESP32** with gas and climate sensors, the system visualizes data through a custom dashboard and triggers automated hazard responses.

## Key Features
* **Real-time Monitoring**: Continuous tracking of gas levels, temperature, and humidity.
* **Automated Alerts**: Triggers instant **LINE notifications** via **n8n** when sensors detect levels exceeding safety thresholds.
* **Data Visualization**: A custom-built dashboard for monitoring environmental trends.

## Technical Stack
* **Hardware**: ESP32, MQ-2 Gas Sensor, DHT11 Temperature/Humidity Sensor.
* **Firmware/Backend**: Arduino (C++), FastAPI.
* **Automation**: n8n workflow integration.
* **Communication**: MQTT Protocol & LINE Notify API.

## Installation & Setup
1. Clone this repository.
2. Create a `.env` file based on the provided `.env.example` template.
3. Fill in your own credentials (Wi-Fi, MQTT Broker, LINE Token).
4. Deploy the code to your ESP32 and start the FastAPI server.

## Security Note
Sensitive information such as API keys and passwords are managed via environment variables and are **not** stored in this repository.
