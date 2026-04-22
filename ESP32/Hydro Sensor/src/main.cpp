#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <WebServer.h>
#include <ArduinoJson.h>
#include "secrets.h"

#define READ_INTERVAL_MS 30000
#define CONFIG_PULL_INTERVAL_MS 300000
#define SERVER_PORT 9731
#define DISCOVERY_URL "http://10.0.0.228:9731/api/sensors/esp32/discover"
#define CONFIG_URL "http://10.0.0.228:9731/api/sensors/esp32/"
#define READINGS_URL "http://10.0.0.228:9731/api/sensors/readings"
#define LED_PIN 2

WebServer server(SERVER_PORT);

struct Sensor {
    const char* name;
    const char* type;
    uint8_t pin;
    float offset;
    float scale;
    bool enabled;
};

Sensor sensors[10];
int sensorCount = 0;

unsigned long lastRead = 0;
unsigned long lastConfigPull = 0;
int myDeviceId = -1;

void blinkLed(int times, int delayMs);
void discoverToServer();
void pullConfigFromServer();
void pushSensorsToServer();
void handleSensorList();
void handleSensorConfig();
void handleTrigger();
float readSensor(Sensor* s);
void addDefaultSensors();
void sendReadingToServer();

void blinkLed(int times, int delayMs) {
    for (int i = 0; i < times; i++) {
        digitalWrite(LED_PIN, HIGH);
        delay(delayMs);
        digitalWrite(LED_PIN, LOW);
        delay(delayMs);
    }
}

void discoverToServer() {
    if (WiFi.status() != WL_CONNECTED) return;
    
    HTTPClient http;
    http.begin(DISCOVERY_URL);
    http.addHeader("Content-Type", "application/json");
    
    StaticJsonDocument<256> doc;
    doc["device_name"] = "ESP32-Hydro";
    doc["mac_address"] = WiFi.macAddress();
    
    String payload;
    serializeJson(doc, payload);
    
    int code = http.POST(payload);
    if (code == 200 || code == 201) {
        StaticJsonDocument<64> response;
        deserializeJson(response, http.getString());
        myDeviceId = response["id"].as<int>();
        Serial.print("[Discovery] Registered with ID: ");
        Serial.println(myDeviceId);
    }
    http.end();
}

void pullConfigFromServer() {
    if (WiFi.status() != WL_CONNECTED || myDeviceId < 0) return;

    char url[128];
    snprintf(url, sizeof(url), "%s%d/config", CONFIG_URL, myDeviceId);
    
    HTTPClient http;
    http.begin(url);
    
    int code = http.GET();
    if (code == 200) {
        StaticJsonDocument<1024> doc;
        deserializeJson(doc, http.getString());
        
        JsonArray sensorConfigs = doc["sensors"];
        sensorCount = 0;
        
        for (JsonObject s : sensorConfigs) {
            if (sensorCount >= 10) break;
            
            sensors[sensorCount].name = strdup(s["name"].as<const char*>());
            sensors[sensorCount].type = strdup(s["sensor_type"].as<const char*>());
            sensors[sensorCount].pin = s["pin_number"].as<uint8_t>();
            sensors[sensorCount].offset = s["calibration_offset"].as<float>();
            sensors[sensorCount].scale = s["calibration_scale"].as<float>();
            sensors[sensorCount].enabled = true;
            
            pinMode(sensors[sensorCount].pin, INPUT);
            
            Serial.print("[Pull] Sensor: ");
            Serial.print(sensors[sensorCount].name);
            Serial.print(" on pin ");
            Serial.println(sensors[sensorCount].pin);
            
            sensorCount++;
        }
        Serial.println("[Pull] Config updated from server");
    }
    http.end();
}

void pushSensorsToServer() {
    if (WiFi.status() != WL_CONNECTED || myDeviceId < 0) return;

    char url[128];
    snprintf(url, sizeof(url), "%s%d/sensors", CONFIG_URL, myDeviceId);
    
    HTTPClient http;
    http.begin(url);
    http.addHeader("Content-Type", "application/json");
    
    StaticJsonDocument<512> doc;
    JsonArray sensorsArray = doc.createNestedArray("sensors");
    
    for (int i = 0; i < sensorCount; i++) {
        JsonObject s = sensorsArray.createNestedObject();
        s["name"] = sensors[i].name;
        s["sensor_type"] = sensors[i].type;
        s["pin_number"] = sensors[i].pin;
    }
    
    String payload;
    serializeJson(doc, payload);
    
    int code = http.POST(payload);
    if (code == 200 || code == 201) {
        Serial.println("[Push] Sensors pushed to server");
    } else {
        Serial.print("[Push] Failed: ");
        Serial.println(code);
    }
    http.end();
}

void handleSensorList() {
    StaticJsonDocument<512> doc;
    JsonArray sensorsArray = doc.createNestedArray("sensors");
    
    for (int i = 0; i < sensorCount; i++) {
        JsonObject s = sensorsArray.createNestedObject();
        s["name"] = sensors[i].name;
        s["sensor_type"] = sensors[i].type;
        s["pin_number"] = sensors[i].pin;
    }
    
    String output;
    serializeJson(doc, output);
    server.send(200, "application/json", output);
}

void handleSensorConfig() {
    if (!server.hasArg("plain")) {
        server.send(400, "application/json", "{\"error\":\"No data\"}");
        return;
    }
    
    String body = server.arg("plain");
    StaticJsonDocument<1024> doc;
    DeserializationError error = deserializeJson(doc, body);
    
    if (error) {
        server.send(400, "application/json", "{\"error\":\"Invalid JSON\"}");
        return;
    }
    
    JsonArray sensorConfigs = doc["sensors"];
    sensorCount = 0;
    
    for (JsonObject s : sensorConfigs) {
        if (sensorCount >= 10) break;
        
        sensors[sensorCount].name = strdup(s["name"].as<const char*>());
        sensors[sensorCount].type = strdup(s["sensor_type"].as<const char*>());
        sensors[sensorCount].pin = s["pin_number"].as<uint8_t>();
        sensors[sensorCount].offset = s["calibration_offset"].as<float>();
        sensors[sensorCount].scale = s["calibration_scale"].as<float>();
        sensors[sensorCount].enabled = true;
        
        pinMode(sensors[sensorCount].pin, INPUT);
        
        Serial.print("[Config] Sensor: ");
        Serial.print(sensors[sensorCount].name);
        Serial.print(" on pin ");
        Serial.println(sensors[sensorCount].pin);
        
        sensorCount++;
    }
    
    server.send(200, "application/json", "{\"status\":\"ok\"}");
}

void handleTrigger() {
    server.send(200, "application/json", "{\"status\":\"ok\"}");
    sendReadingToServer();
}

float readSensor(Sensor* s) {
    int samples = 10;
    long total = 0;
    for (int i = 0; i < samples; i++) {
        total += analogRead(s->pin);
        delayMicroseconds(100);
    }
    float raw = total / (float)samples;
    return (raw * s->scale) + s->offset;
}

void setup() {
    Serial.begin(115200);
    delay(1000);
    
    Serial.println();
    Serial.println("=== ESP32 Hydro Sensor ===");
    
    pinMode(LED_PIN, OUTPUT);
    blinkLed(2, 100);
    
    sensorCount = 0;
    
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.print("Connecting to WiFi");
    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 30) {
        delay(500);
        Serial.print(".");
        attempts++;
    }
    
    if (WiFi.status() == WL_CONNECTED) {
        Serial.println();
        Serial.print("WiFi connected! IP: ");
        Serial.println(WiFi.localIP());
        blinkLed(3, 100);
        
        discoverToServer();
        
        if (myDeviceId > 0) {
            pullConfigFromServer();
            if (sensorCount == 0) {
                Serial.println("No sensors from server, using default config");
                addDefaultSensors();
            }
        } else {
            addDefaultSensors();
        }
    } else {
        Serial.println();
        Serial.println("WiFi connection failed!");
        addDefaultSensors();
        blinkLed(10, 100);
    }
    
    lastRead = millis();
    lastConfigPull = millis();
    
    server.on("/api/sensors/list", HTTP_GET, handleSensorList);
    server.on("/api/sensors/config", HTTP_POST, handleSensorConfig);
    server.on("/api/sensors/trigger", HTTP_POST, handleTrigger);
    server.begin();
    Serial.print("HTTP server started on port ");
    Serial.println(SERVER_PORT);
    
    Serial.println("Ready!");
}

void addDefaultSensors() {
    sensors[0].name = "Water Level A1";
    sensors[0].type = "capacitive";
    sensors[0].pin = 34;
    sensors[0].offset = 0.0f;
    sensors[0].scale = 1.0f;
    sensors[0].enabled = true;
    pinMode(34, INPUT);
    
    sensors[1].name = "Soil Moisture A2";
    sensors[1].type = "capacitive";
    sensors[1].pin = 35;
    sensors[1].offset = 0.0f;
    sensors[1].scale = 1.0f;
    sensors[1].enabled = true;
    pinMode(35, INPUT);
    
    sensorCount = 2;
    
    Serial.println("Using default sensor config");
}

void loop() {
    unsigned long now = millis();
    
    if (now - lastConfigPull >= CONFIG_PULL_INTERVAL_MS) {
        if (WiFi.status() != WL_CONNECTED) {
            Serial.println("Reconnecting WiFi...");
            WiFi.reconnect();
            delay(1000);
        }
        
        if (myDeviceId > 0) {
            pullConfigFromServer();
        }
        lastConfigPull = now;
    }
    
    if (now - lastRead >= READ_INTERVAL_MS) {
        if (WiFi.status() != WL_CONNECTED) {
            Serial.println("Reconnecting WiFi...");
            WiFi.reconnect();
            delay(1000);
        }
        
        if (WiFi.status() == WL_CONNECTED) {
            HTTPClient http;
            http.begin(READINGS_URL);
            http.addHeader("Content-Type", "application/json");
            
            StaticJsonDocument<512> doc;
            doc["device"] = WiFi.localIP().toString();
            doc["esp32_id"] = myDeviceId;
            JsonArray readings = doc.createNestedArray("readings");
            
            for (int i = 0; i < sensorCount; i++) {
                if (!sensors[i].enabled) continue;
                
                float value = readSensor(&sensors[i]);
                JsonObject r = readings.createNestedObject();
                r["sensor"] = sensors[i].name;
                r["value"] = value;
                r["unit"] = "raw";
                
                Serial.print("[");
                Serial.print(sensors[i].name);
                Serial.print("] = ");
                Serial.println(value);
            }
            
            String payload;
            serializeJson(doc, payload);
            
            int httpCode = http.POST(payload);
            http.end();
            
            if (httpCode > 0) {
                Serial.print("Sent: ");
                Serial.println(httpCode);
            } else {
                Serial.print("Send failed: ");
                Serial.println(httpCode);
            }
        }
        
        lastRead = now;
    }
    
    delay(100);
    server.handleClient();
}

void sendReadingToServer() {
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("[Trigger] WiFi not connected");
        return;
    }
    
    HTTPClient http;
    http.begin(READINGS_URL);
    http.addHeader("Content-Type", "application/json");
    
    StaticJsonDocument<512> doc;
    doc["device"] = WiFi.localIP().toString();
    doc["esp32_id"] = myDeviceId;
    JsonArray readings = doc.createNestedArray("readings");
    
    for (int i = 0; i < sensorCount; i++) {
        if (!sensors[i].enabled) continue;
        
        float value = readSensor(&sensors[i]);
        JsonObject r = readings.createNestedObject();
        r["sensor"] = sensors[i].name;
        r["value"] = value;
        r["unit"] = "raw";
        
        Serial.print("[Trigger] ");
        Serial.print(sensors[i].name);
        Serial.print(" = ");
        Serial.println(value);
    }
    
    String payload;
    serializeJson(doc, payload);
    
    int httpCode = http.POST(payload);
    http.end();
    
    if (httpCode > 0) {
        Serial.print("[Trigger] Sent: ");
        Serial.println(httpCode);
    } else {
        Serial.print("[Trigger] Failed: ");
        Serial.println(httpCode);
    }
}