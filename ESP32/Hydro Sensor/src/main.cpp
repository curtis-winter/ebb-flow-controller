#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <WebServer.h>
#include <Preferences.h>
#include <ArduinoJson.h>
#include "secrets.h"

#define READ_INTERVAL_MS_DEFAULT 30000
#define CONFIG_PULL_INTERVAL_MS 300000
#define DEFAULT_SERVER_PORT 9731
#define LED_PIN 2
#define DEFAULT_WEB_REFRESH_MS 1000  // Default web UI refresh rate (1 second)

WebServer configServer(80);
Preferences preferences;

struct Sensor {
    char name[32];
    char type[16];
    uint8_t pin;
    float offset;
    float scale;
    bool enabled;
};

Sensor sensors[10];
int sensorCount = 0;

unsigned long lastRead = 0;
unsigned long lastConfigPull = 0;
unsigned long readIntervalMs = READ_INTERVAL_MS_DEFAULT;
unsigned long webRefreshMs = DEFAULT_WEB_REFRESH_MS; // Web UI refresh rate
int myDeviceId = -1;

char serverIp[16] = "10.0.0.228";
int serverPort = DEFAULT_SERVER_PORT;
char wifiSsid[32] = WIFI_SSID;
char wifiPassword[64] = WIFI_PASSWORD;

void blinkLed(int times, int delayMs);
void handleRoot();
void handleSaveConfig();
void handleSensorList();
void handleSensorConfig();
void handleTrigger();
void handleNotFound();
void handleSensorReadings();
float readSensor(Sensor* s);
void addDefaultSensors();
void sendReadingToServer();
void loadConfig();
void saveConfig();

void blinkLed(int times, int delayMs) {
    for (int i = 0; i < times; i++) {
        digitalWrite(LED_PIN, HIGH);
        delay(delayMs);
        digitalWrite(LED_PIN, LOW);
        delay(delayMs);
    }
}

void loadConfig() {
    preferences.begin("esp32-sensor", false);
    preferences.getString("serverIp", serverIp, sizeof(serverIp));
    if (strlen(serverIp) == 0) strcpy(serverIp, "10.0.0.228");
    serverPort = preferences.getInt("serverPort", DEFAULT_SERVER_PORT);
    if (serverPort == 0) serverPort = DEFAULT_SERVER_PORT;
    preferences.getString("wifiSsid", wifiSsid, sizeof(wifiSsid));
    if (strlen(wifiSsid) == 0) strcpy(wifiSsid, WIFI_SSID);
    preferences.getString("wifiPass", wifiPassword, sizeof(wifiPassword));
    if (strlen(wifiPassword) == 0) strcpy(wifiPassword, WIFI_PASSWORD);
    
    readIntervalMs = preferences.getInt("readIntervalMs", READ_INTERVAL_MS_DEFAULT);
    if (readIntervalMs < 5000) readIntervalMs = 5000;
    if (readIntervalMs > 3600000) readIntervalMs = 3600000;
    
    webRefreshMs = preferences.getInt("webRefreshMs", DEFAULT_WEB_REFRESH_MS);
    if (webRefreshMs < 100) webRefreshMs = 100;
    if (webRefreshMs > 10000) webRefreshMs = 10000;
    
    sensorCount = preferences.getInt("sensorCount", 0);
    if (sensorCount == 0) {
        addDefaultSensors();
        saveConfig();
        sensorCount = preferences.getInt("sensorCount", 0);
    } else {
        for (int i = 0; i < sensorCount && i < 10; i++) {
            String key = "sensor" + String(i);
            String sensorJson = preferences.getString(key.c_str(), "");
            if (sensorJson.length() > 0) {
                StaticJsonDocument<256> doc;
                DeserializationError error = deserializeJson(doc, sensorJson);
                if (!error) {
                    strlcpy(sensors[i].name, doc["name"] | "Sensor", sizeof(sensors[i].name));
                    strlcpy(sensors[i].type, doc["type"] | "capacitive", sizeof(sensors[i].type));
                    sensors[i].pin = doc["pin"] | 34;
                    sensors[i].offset = doc["offset"] | 0.0f;
                    sensors[i].scale = doc["scale"] | 1.0f;
                    sensors[i].enabled = doc["enabled"] | true;
                }
            }
        }
    }
    preferences.end();
    
    Serial.println("Loaded config:");
    Serial.print("  Server: ");
    Serial.print(serverIp);
    Serial.print(":");
    Serial.println(serverPort);
    Serial.print("  WiFi: ");
    Serial.println(wifiSsid);
Serial.print(" Read Interval: ");
    Serial.print(readIntervalMs);
    Serial.println("ms");
    Serial.print(" Web Refresh: ");
    Serial.print(webRefreshMs);
    Serial.println("ms");
    Serial.print("  Sensors: ");
    Serial.println(sensorCount);
}

void saveConfig() {
    preferences.begin("esp32-sensor", false);
    preferences.putString("serverIp", serverIp);
    preferences.putInt("serverPort", serverPort);
    preferences.putString("wifiSsid", wifiSsid);
    preferences.putString("wifiPass", wifiPassword);
    preferences.putInt("readIntervalMs", readIntervalMs);
    preferences.putInt("webRefreshMs", webRefreshMs);
    preferences.putInt("sensorCount", sensorCount);
    
    for (int i = 0; i < sensorCount; i++) {
        StaticJsonDocument<256> doc;
        doc["name"] = sensors[i].name;
        doc["type"] = sensors[i].type;
        doc["pin"] = sensors[i].pin;
        doc["offset"] = sensors[i].offset;
        doc["scale"] = sensors[i].scale;
        doc["enabled"] = sensors[i].enabled;
        String key = "sensor" + String(i);
        String sensorJson;
        serializeJson(doc, sensorJson);
        preferences.putString(key.c_str(), sensorJson);
    }
    preferences.end();
    Serial.println("Config saved!");
}

void handleRoot() {
  String html = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ESP32 Sensor Config</title>
<style>
body { font-family: Arial, sans-serif; max-width: 800px; margin: 20px auto; padding: 20px; background: #1a1a2e; color: #eee; }
h1 { color: #00d4ff; }
h2 { color: #ffb703; margin-top: 30px; }
.form-group { margin-bottom: 15px; }
label { display: block; margin-bottom: 5px; font-weight: bold; }
input, select { width: 100%; padding: 10px; border-radius: 5px; border: 1px solid #333; background: #2a2a4a; color: #fff; box-sizing: border-box; }
button { background: #00d4ff; color: #000; padding: 12px 24px; border: none; border-radius: 5px; cursor: pointer; font-size: 16px; font-weight: bold; margin-top: 10px; }
button:hover { background: #00a8cc; }
.sensor-card { background: #2a2a4a; padding: 15px; margin: 10px 0; border-radius: 5px; }
.sensor-card h3 { margin: 0 0 10px 0; color: #ffb703; }
.info { background: #2a2a4a; padding: 10px; border-radius: 5px; margin-bottom: 20px; }
.sensor-value { font-size: 24px; color: #00d4ff; font-weight: bold; }
.sensor-reading { color: #888; font-size: 14px; }
.btn-small { padding: 6px 12px; font-size: 12px; margin: 2px; }
.btn-danger { background: #ff4757; }
.btn-danger:hover { background: #ff6b81; }
.tabs { display: flex; gap: 10px; margin-bottom: 20px; }
.tab { padding: 10px 20px; background: #2a2a4a; border: none; border-radius: 5px; cursor: pointer; }
.tab.active { background: #00d4ff; color: #000; }
.tab-content { display: none; }
.tab-content.active { display: block; }
.live-reading { background: #2a2a4a; padding: 15px; margin: 10px 0; border-radius: 5px; border-left: 4px solid #00d4ff; }
.live-reading h3 { margin: 0 0 5px 0; color: #ffb703; }
.live-value { font-size: 28px; color: #00d4ff; font-weight: bold; }
.live-type { color: #888; font-size: 12px; }
</style>
</head>
<body>
<h1>🌡️ ESP32 Sensor Config</h1>

<div class="info">
<strong>Status:</strong> )rawliteral";
  html += WiFi.status() == WL_CONNECTED ? "Connected" : "Disconnected";
  html += R"rawliteral(<br>
<strong>IP:</strong> )rawliteral";
  html += WiFi.localIP().toString();
  html += R"rawliteral(<br>
<strong>MAC:</strong> )rawliteral";
  html += WiFi.macAddress();
  html += R"rawliteral(
</div>

<div class="tabs">
<button class="tab active" onclick="showTab('readings')">📊 Live Readings</button>
<button class="tab" onclick="showTab('config')">⚙️ Configuration</button>
</div>

<div id="readings" class="tab-content active">
<h2>📊 Live Sensor Readings</h2>
<div id="liveReadings"></div>
<button onclick="refreshReadings()" class="btn-small">🔄 Refresh Now</button>
</div>

<div id="config" class="tab-content">
<form action="/save" method="POST">
<h2>📶 WiFi Settings</h2>
<div class="form-group">
<label>SSID</label>
<input type="text" name="wifiSsid" value=")rawliteral";
  html += wifiSsid;
  html += R"rawliteral(" required>
</div>
<div class="form-group">
<label>Password</label>
<input type="password" name="wifiPass" value=")rawliteral";
  html += wifiPassword;
  html += R"rawliteral(">
</div>

<h2>🖥️ FlowBoard Server</h2>
<div class="form-group">
<label>Server IP Address</label>
<input type="text" name="serverIp" value=")rawliteral";
  html += serverIp;
  html += R"rawliteral(" required pattern="[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}">
</div>
<div class="form-group">
<label>Server Port</label>
<input type="number" name="serverPort" value=")rawliteral";
  html += String(serverPort);
  html += R"rawliteral(" required min="1" max="65535">
</div>
<div class="form-group">
<label>Read Interval (seconds)</label>
<input type="number" name="readIntervalSec" value=")rawliteral";
html += String(readIntervalMs / 1000);
html += R"rawliteral(" required min="5" max="3600">
</div>
<div class="form-group">
<label>Web UI Refresh Rate (ms)</label>
<input type="number" name="webRefreshMs" value=")rawliteral";
html += String(webRefreshMs);
html += R"rawliteral(" required min="100" max="10000" step="100">
<div style="font-size: 11px; color: #888; margin-top: 4px;">Update frequency for live readings (100ms-10s). Lower = faster but more battery use.</div>
</div>

<button type="submit">💾 Save Configuration</button>
</form>

<h2>🌡️ Sensor Configuration</h2>
<div class="form-group">
<label>Number of Sensors</label>
<input type="number" name="sensorCount" value=")rawliteral";
  html += String(sensorCount);
  html += R"rawliteral(" min="0" max="10" id="sensorCount" onchange="updateSensorFields()">
</div>
<div id="sensorFields">
)";

char buf[512];
for (int i = 0; i < 10; i++) {
if (i < sensorCount) {
  snprintf(buf, sizeof(buf),
  "<div class=\"sensor-card\">"
  "<h3>Sensor %d</h3>"
  "<div class=\"form-group\"><label>Name</label><input type=\"text\" name=\"sensor%d_name\" value=\"%s\"></div>"
  "<div class=\"form-group\"><label>Type</label>"
  "<select name=\"sensor%d_type\">"
  "<option value=\"capacitive\" %s>Capacitive</option>"
  "<option value=\"analog\" %s>Analog</option>"
  "<option value=\"digital\" %s>Digital</option>"
  "<option value=\"ds18b20\" %s>DS18B20</option>"
  "<option value=\"dht22\" %s>DHT22</option></select></div>"
  "<div class=\"form-group\"><label>GPIO Pin (ADC1: 34,35,36,39 recommended)</label>"
  "<input type=\"number\" name=\"sensor%d_pin\" value=\"%d\" min=\"0\" max=\"39\"></div>"
  "<div class=\"form-group\"><label>Calibration Offset</label>"
  "<input type=\"number\" name=\"sensor%d_offset\" value=\"%.2f\" step=\"0.1\"></div>"
  "<div class=\"form-group\"><label>Calibration Scale</label>"
  "<input type=\"number\" name=\"sensor%d_scale\" value=\"%.2f\" step=\"0.01\"></div>"
  "</div>",
  i + 1, i, sensors[i].name, i,
  strcmp(sensors[i].type, "capacitive") == 0 ? "selected" : "",
  strcmp(sensors[i].type, "analog") == 0 ? "selected" : "",
  strcmp(sensors[i].type, "digital") == 0 ? "selected" : "",
  strcmp(sensors[i].type, "ds18b20") == 0 ? "selected" : "",
  strcmp(sensors[i].type, "dht22") == 0 ? "selected" : "",
  i, sensors[i].pin, i, sensors[i].offset, i, sensors[i].scale);
  html += buf;
}
}

html += R"rawliteral(</div>
<button type="submit">💾 Save Configuration</button>
</form>
</div>

<script>
function showTab(tabName) {
document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
const btn = Array.from(document.querySelectorAll('.tab')).find(b => b.textContent.toLowerCase().includes(tabName.split('-')[0] || tabName));
if (btn) btn.classList.add('active');
document.getElementById(tabName).classList.add('active');
if (tabName === 'readings') refreshReadings();
}

function updateSensorFields() {
alert('Note: Changing sensor count will require saving and rebooting.');
}

async function refreshReadings() {
try {
const res = await fetch('/api/sensor/readings');
const data = await res.json();
const div = document.getElementById('liveReadings');
if (data.sensors && data.sensors.length > 0) {
div.innerHTML = data.sensors.map(s =>
'<div class="live-reading">' +
'<h3>' + s.name + '</h3>' +
'<div class="live-value">' + s.value.toFixed(1) + '</div>' +
'<div class="live-type">Type: ' + s.type + ' | GPIO: ' + s.pin + '</div>' +
'</div>'
).join('');
} else {
div.innerHTML = '<p>No sensors configured</p>';
}
} catch (e) {
console.error('Failed to refresh:', e);
}
}

// Auto-refresh readings based on configured refresh rate
const REFRESH_RATE = )rawliteral";
html += String(webRefreshMs);
html += R"rawliteral(;
setInterval(() => {
if (document.getElementById('readings').classList.contains('active')) {
refreshReadings();
}
}, REFRESH_RATE);
</script>
</body>
</html>
)rawliteral";

configServer.send(200, "text/html", html);
}

void handleSaveConfig() {
    if (configServer.hasArg("wifiSsid")) {
        configServer.arg("wifiSsid").toCharArray(wifiSsid, sizeof(wifiSsid));
    }
    if (configServer.hasArg("wifiPass")) {
        configServer.arg("wifiPass").toCharArray(wifiPassword, sizeof(wifiPassword));
    }
    if (configServer.hasArg("serverIp")) {
        configServer.arg("serverIp").toCharArray(serverIp, sizeof(serverIp));
    }
    if (configServer.hasArg("serverPort")) {
        serverPort = configServer.arg("serverPort").toInt();
    }
    if (configServer.hasArg("readIntervalSec")) {
        int intervalSec = configServer.arg("readIntervalSec").toInt();
        if (intervalSec >= 5 && intervalSec <= 3600) {
            readIntervalMs = intervalSec * 1000;
        }
    }
    if (configServer.hasArg("webRefreshMs")) {
        webRefreshMs = configServer.arg("webRefreshMs").toInt();
        if (webRefreshMs < 100) webRefreshMs = 100;
        if (webRefreshMs > 10000) webRefreshMs = 10000;
    }
    if (configServer.hasArg("sensorCount")) {
        sensorCount = configServer.arg("sensorCount").toInt();
        if (sensorCount < 0) sensorCount = 0;
        if (sensorCount > 10) sensorCount = 10;
    }
    
    for (int i = 0; i < sensorCount; i++) {
        String nameKey = "sensor" + String(i) + "_name";
        String typeKey = "sensor" + String(i) + "_type";
        String pinKey = "sensor" + String(i) + "_pin";
        String offsetKey = "sensor" + String(i) + "_offset";
        String scaleKey = "sensor" + String(i) + "_scale";
        
        if (configServer.hasArg(nameKey)) {
            configServer.arg(nameKey).toCharArray(sensors[i].name, sizeof(sensors[i].name));
        }
        if (configServer.arg(typeKey).length() > 0) {
            configServer.arg(typeKey).toCharArray(sensors[i].type, sizeof(sensors[i].type));
        }
        if (configServer.hasArg(pinKey)) {
            sensors[i].pin = configServer.arg(pinKey).toInt();
        }
        if (configServer.hasArg(offsetKey)) {
            sensors[i].offset = configServer.arg(offsetKey).toFloat();
        }
        if (configServer.hasArg(scaleKey)) {
            sensors[i].scale = configServer.arg(scaleKey).toFloat();
        }
        sensors[i].enabled = true;
    }
    
    saveConfig();
    
    String html = R"rawliteral(<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta http-equiv="refresh" content="3;url=/">
    <title>ESP32 - Saved</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 600px; margin: 20px auto; padding: 20px; background: #1a1a2e; color: #eee; text-align: center; }
        h1 { color: #00ff88; }
        a { color: #00d4ff; }
    </style>
</head>
<body>
    <h1>✅ Configuration Saved!</h1>
    <p>Settings saved. Redirecting...</p>
</body>
</html>)rawliteral";
    configServer.send(200, "text/html", html);
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
    configServer.send(200, "application/json", output);
}

void handleSensorConfig() {
    if (!configServer.hasArg("plain")) {
        configServer.send(400, "application/json", "{\"error\":\"No data\"}");
        return;
    }
    
    String body = configServer.arg("plain");
    StaticJsonDocument<1024> doc;
    DeserializationError error = deserializeJson(doc, body);
    
    if (error) {
        configServer.send(400, "application/json", "{\"error\":\"Invalid JSON\"}");
        return;
    }
    
    if (doc.containsKey("update_rate")) {
        int intervalSec = doc["update_rate"].as<int>();
        if (intervalSec >= 5 && intervalSec <= 3600) {
            readIntervalMs = intervalSec * 1000;
            preferences.begin("esp32-sensor", false);
            preferences.putInt("readIntervalMs", readIntervalMs);
            preferences.end();
            Serial.print("[Config] Update rate: ");
            Serial.print(intervalSec);
            Serial.println("s (saved)");
        }
    }
    
    if (!doc.containsKey("sensors")) {
        configServer.send(200, "application/json", "{\"status\":\"ok\"}");
        return;
    }
    
    JsonArray sensorConfigs = doc["sensors"];
    sensorCount = 0;
    
    for (JsonObject s : sensorConfigs) {
        if (sensorCount >= 10) break;
        
        strlcpy(sensors[sensorCount].name, s["name"] | "Sensor", sizeof(sensors[sensorCount].name));
        strlcpy(sensors[sensorCount].type, s["sensor_type"] | "capacitive", sizeof(sensors[sensorCount].type));
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
    
    configServer.send(200, "application/json", "{\"status\":\"ok\"}");
}

void handleSensorReadings() {
    StaticJsonDocument<1024> doc;
    JsonArray sensorsArray = doc.createNestedArray("sensors");
    
    for (int i = 0; i < sensorCount; i++) {
        if (!sensors[i].enabled) continue;
        
        float value = readSensor(&sensors[i]);
        JsonObject s = sensorsArray.createNestedObject();
        s["name"] = sensors[i].name;
        s["type"] = sensors[i].type;
        s["pin"] = sensors[i].pin;
        s["value"] = value;
        s["offset"] = sensors[i].offset;
        s["scale"] = sensors[i].scale;
    }
    
    String output;
    serializeJson(doc, output);
    configServer.send(200, "application/json", output);
}

void handleTrigger() {
    configServer.send(200, "application/json", "{\"status\":\"ok\"}");
    sendReadingToServer();
}

void handleNotFound() {
    configServer.send(404, "text/plain", "Not Found");
}

void discoverToServer() {
    if (WiFi.status() != WL_CONNECTED) return;
    
    char url[128];
    snprintf(url, sizeof(url), "http://%s:%d/api/sensors/esp32/discover", serverIp, serverPort);
    
    HTTPClient http;
    http.begin(url);
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
    snprintf(url, sizeof(url), "http://%s:%d/api/sensors/esp32/%d/config", serverIp, serverPort, myDeviceId);
    
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
            
            strlcpy(sensors[sensorCount].name, s["name"] | "Sensor", sizeof(sensors[sensorCount].name));
            strlcpy(sensors[sensorCount].type, s["sensor_type"] | "capacitive", sizeof(sensors[sensorCount].type));
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
    snprintf(url, sizeof(url), "http://%s:%d/api/sensors/esp32/%d/sensors", serverIp, serverPort, myDeviceId);
    
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

float readSensor(Sensor* s) {
  int samples = 10;
  long total = 0;
  for (int i = 0; i < samples; i++) {
    total += analogRead(s->pin);
    yield(); // Allow WiFi stack to process
    delayMicroseconds(100);
  }
  float raw = total / (float)samples;
  return (raw * s->scale) + s->offset;
}

void sendReadingToServer() {
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("[Trigger] WiFi not connected");
        return;
    }
    
    char url[128];
    snprintf(url, sizeof(url), "http://%s:%d/api/sensors/readings", serverIp, serverPort);
    
    HTTPClient http;
    http.begin(url);
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

void addDefaultSensors() {
  strcpy(sensors[0].name, "Water Level A1");
  strcpy(sensors[0].type, "capacitive");
  sensors[0].pin = 34;
  sensors[0].offset = 0.0f;
  sensors[0].scale = 1.0f;
  sensors[0].enabled = true;
  pinMode(34, INPUT);

  strcpy(sensors[1].name, "Soil Moisture A2");
  strcpy(sensors[1].type, "capacitive");
  sensors[1].pin = 35;
  sensors[1].offset = 0.0f;
  sensors[1].scale = 1.0f;
  sensors[1].enabled = true;
  pinMode(35, INPUT);

  strcpy(sensors[2].name, "Water Level 2");
  strcpy(sensors[2].type, "capacitive");
  sensors[2].pin = 36;
  sensors[2].offset = 0.0f;
  sensors[2].scale = 1.0f;
  sensors[2].enabled = true;
  pinMode(36, INPUT);

  strcpy(sensors[3].name, "Pot 1");
  strcpy(sensors[3].type, "capacitive");
  sensors[3].pin = 39;
  sensors[3].offset = 0.0f;
  sensors[3].scale = 1.0f;
  sensors[3].enabled = true;
  pinMode(39, INPUT);

  sensorCount = 4;

  Serial.println("Using default sensor config (ADC1 pins: 34, 35, 36, 39)");
}

void setup() {
    Serial.begin(115200);
    delay(1000);
    
    Serial.println();
    Serial.println("=== ESP32 Hydro Sensor ===");
    
    pinMode(LED_PIN, OUTPUT);
    blinkLed(2, 100);
    
    loadConfig();
    
    sensorCount = 0;
    for (int i = 0; i < 10; i++) {
        if (sensors[i].enabled && sensors[i].pin > 0) {
            pinMode(sensors[i].pin, INPUT);
            sensorCount++;
        }
    }
    if (sensorCount == 0) {
        addDefaultSensors();
    }
    
    Serial.println("Connecting to WiFi...");
    WiFi.begin(wifiSsid, wifiPassword);
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
        }
    } else {
        Serial.println();
        Serial.println("WiFi connection failed!");
        blinkLed(10, 100);
    }
    
    lastRead = millis();
    lastConfigPull = millis();
    
    configServer.on("/", handleRoot);
    configServer.on("/save", HTTP_POST, handleSaveConfig);
    configServer.on("/api/sensors/list", HTTP_GET, handleSensorList);
    configServer.on("/api/sensors/config", HTTP_POST, handleSensorConfig);
    configServer.on("/api/sensors/trigger", HTTP_POST, handleTrigger);
    configServer.on("/api/sensor/readings", HTTP_GET, handleSensorReadings);
    configServer.onNotFound(handleNotFound);
    configServer.begin();
    Serial.println("Config web server started on port 80");
    
    Serial.println("Ready!");
}

void loop() {
  configServer.handleClient();
  yield(); // Allow WiFi stack to process

  unsigned long now = millis();

  // Periodically check WiFi connection and restart web server if needed
  static unsigned long lastWifiCheck = 0;
  if (now - lastWifiCheck > 60000) { // Check every minute
    lastWifiCheck = now;
    if (WiFi.status() != WL_CONNECTED) {
      Serial.println("WiFi disconnected, reconnecting...");
      WiFi.reconnect();
      delay(1000);
    }
  }

  // Check for serial commands
  if (Serial.available() > 0) {
        String command = Serial.readStringUntil('\n');
        command.trim();
        if (command == "readings") {
            Serial.println("\n=== Current Sensor Readings ===");
            for (int i = 0; i < sensorCount; i++) {
                if (sensors[i].enabled) {
                    float value = readSensor(&sensors[i]);
                    Serial.print("Sensor ");
                    Serial.print(i + 1);
                    Serial.print(" (");
                    Serial.print(sensors[i].name);
                    Serial.print("): ");
                    Serial.print(value, 2);
                    Serial.println();
                }
            }
            Serial.println("===============================\n");
        } else if (command == "help") {
            Serial.println("\nAvailable commands:");
            Serial.println("  readings - Show current sensor readings");
            Serial.println("  config   - Show current configuration");
            Serial.println("  help     - Show this help message\n");
        } else if (command == "config") {
            Serial.println("\n=== Configuration ===");
            Serial.print("Server: ");
            Serial.print(serverIp);
            Serial.print(":");
            Serial.println(serverPort);
            Serial.print("WiFi: ");
            Serial.println(wifiSsid);
            Serial.print("Sensors: ");
            Serial.println(sensorCount);
            for (int i = 0; i < sensorCount; i++) {
                Serial.print("  ");
                Serial.print(i + 1);
                Serial.print(". ");
                Serial.print(sensors[i].name);
                Serial.print(" (GPIO ");
                Serial.print(sensors[i].pin);
                Serial.print(", ");
                Serial.print(sensors[i].type);
                Serial.println(")");
            }
            Serial.println("=====================\n");
        }
    }
    
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
    
    if (now - lastRead >= readIntervalMs) {
        if (WiFi.status() != WL_CONNECTED) {
            Serial.println("Reconnecting WiFi...");
            WiFi.reconnect();
            delay(1000);
        }
        
        if (WiFi.status() == WL_CONNECTED) {
            sendReadingToServer();
        }
        
        lastRead = now;
    }
    
    delay(100);
}