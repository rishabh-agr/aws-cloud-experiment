#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <U8g2lib.h>
#include <ArduinoJson.h>

// ====== USER CONFIG ======
const char* ssid     = "Rishabh’s iPhone";      // your Wi-Fi / hotspot name
const char* password = "12344321"; // your Wi-Fi password

// POST /predict with JSON { "samples":[ ... ] }
const char* serverUrl = "http://44.192.254.95/predict";
// =========================

// U8g2 for 1.3" SH1106 I2C OLED (4-pin)
// SW I2C: clock = 22, data = 21 (matches your test code)
U8G2_SH1106_128X64_NONAME_F_SW_I2C u8g2(
  U8G2_R0, /* clock=*/ 22, /* data=*/ 21, /* reset=*/ U8X8_PIN_NONE
);

// Pins
const int ECG_PIN      = 34;  // AD8232 OUTPUT
const int LO_POS_PIN   = 32;  // optional LO+
const int LO_NEG_PIN   = 33;  // optional LO-
const int BTN_PIN      = 25;  // start button
const int BUZZER_PIN   = 14;  // active buzzer
const int LED_YELLOW   = 27;  // power / diagnosis
const int LED_GREEN    = 26;  // healthy
const int LED_RED      = 18;  // unhealthy

// Sampling
const int NUM_SAMPLES = 2500;
int samplesArr[NUM_SAMPLES];      // ~10KB

bool diagnosing = false;          // prevents re-trigger
unsigned long lastBlink = 0;
bool yellowState = true;
bool awaitAck = false;

// ------------ OLED helper (3 lines of text) -------------
void oledPrint(const String &l1,
               const String &l2 = "",
               const String &l3 = "") {
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_ncenB08_tr);   // same as your test code

  // y is baseline; choose row heights nicely
  int y1 = 12;
  int y2 = 28;
  int y3 = 44;

  u8g2.drawStr(0, y1, l1.c_str());
  if (l2.length()) u8g2.drawStr(0, y2, l2.c_str());
  if (l3.length()) u8g2.drawStr(0, y3, l3.c_str());

  u8g2.sendBuffer();
}

// ------------ Wi-Fi connect -------------
void connectWiFi() {
  WiFi.begin(ssid, password);
  Serial.print("Connecting to WiFi");
  oledPrint("Connecting to WiFi");

  int timeout = 0;
  while (WiFi.status() != WL_CONNECTED && timeout < 40) { // ~20s
    delay(500);
    Serial.print(".");
    timeout++;
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("Connected! IP: ");
    Serial.println(WiFi.localIP());
    oledPrint("WiFi connected",
              WiFi.localIP().toString(),
              "Welcome to ECGenius");
  } else {
    Serial.println("WiFi connection failed");
    oledPrint("WiFi failed", "Check hotspot");
  }
}

// ------------ ECG recording -------------
void recordECG() {
  Serial.println("Recording ECG for 10 seconds...");
  oledPrint("Taking reading...", "Please stay still");

  unsigned long start = millis();

  for (int i = 0; i < NUM_SAMPLES; i++) {
    samplesArr[i] = analogRead(ECG_PIN); // 0-4095

    // YELLOW LED blink during diagnosis (250ms)
    if (millis() - lastBlink > 250) {
      lastBlink = millis();
      yellowState = !yellowState;
      digitalWrite(LED_YELLOW, yellowState ? HIGH : LOW);
    }

    // Slow buzzer blink: 500ms ON/OFF
    if ((millis() / 500) % 2 == 0) {
      digitalWrite(BUZZER_PIN, HIGH);
    } else {
      digitalWrite(BUZZER_PIN, LOW);
    }

    delay(4); // 4ms * 2500 ≈ 10s
  }

  // Stop buzzer after recording
  digitalWrite(BUZZER_PIN, LOW);

  unsigned long duration = millis() - start;
  Serial.print("Recording done, ms = ");
  Serial.println(duration);
}

// ------------ Build JSON for /predict -------------
String buildJson() {
  String json;
  json.reserve(20000);
  json = "{ \"samples\":[";

  for (int i = 0; i < NUM_SAMPLES; i++) {
    json += String(samplesArr[i]);
    if (i < NUM_SAMPLES - 1) json += ",";
  }
  json += "] }";

  return json;
}

// ------------ Send to AWS -------------
String sendToAWS(const String &json) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi not connected, cannot send");
    oledPrint("No WiFi", "Cannot send data");
    return "";
  }

  HTTPClient http;
  http.begin(serverUrl);
  http.addHeader("Content-Type", "application/json");

  Serial.println("Sending POST /predict...");
  oledPrint("Predicting...", "Sending to server");

  int httpCode = http.POST(json);
  String response = "";

  if (httpCode > 0) {
    Serial.print("HTTP code: ");
    Serial.println(httpCode);
    response = http.getString();
    Serial.println("Response:");
    Serial.println(response);
  } else {
    Serial.print("HTTP error: ");
    Serial.println(http.errorToString(httpCode));
    oledPrint("Server error", http.errorToString(httpCode));
  }

  http.end();
  return response;
}

// ------------ Handle prediction results -------------
void handlePrediction(const String &resp) {
  // Reset LEDs/buzzer first
  digitalWrite(LED_GREEN, LOW);
  digitalWrite(LED_RED,   LOW);
  digitalWrite(BUZZER_PIN, LOW);

  if (resp.length() == 0) {
    oledPrint("No response", "Check server");
    return;
  }

  // Parse JSON
  StaticJsonDocument<1024> doc;
  DeserializationError err = deserializeJson(doc, resp);
  if (err) {
    Serial.print("JSON parse error: ");
    Serial.println(err.c_str());
    oledPrint("Parse error", err.c_str());
    return;
  }

  // ----- NEW FIELD NAMES -----
  JsonObject results = doc["results"];

  float hr      = results["heart_rate"] | 0.0;
  bool af       = results["is_afib"] | false;
  bool bbb      = results["is_bbb"]  | false;
  bool mi       = results["is_mci"]  | false;
  bool vf       = results["is_vfi"]  | false;

  const char* ts       = doc["timestamp"];      // e.g. "2025-11-25T04:58:14.768917+00:00"
  const char* predId   = doc["prediction_id"];  // e.g. "2025-11-25-8e2e5d8a"

  // ----- DETERMINE NORMAL / NOT NORMAL -----
  bool allFalse = !af && !bbb && !mi && !vf;
  bool isNormal = allFalse;

  // ----- BUILD DATE STRING -----
  String dateLine = "Date: ";
  if (ts != nullptr) {
    String tsStr = String(ts);
    if (tsStr.length() >= 10) {
      dateLine += tsStr.substring(0, 10);  // "YYYY-MM-DD"
    } else {
      dateLine += tsStr;
    }
  } else {
    dateLine += "-";
  }

  // ----- BUILD 8-DIGIT ID STRING -----
  String idLine = "ID: ";
  if (predId != nullptr) {
    String pidStr = String(predId);
    int lastDash = pidStr.lastIndexOf('-');
    if (lastDash >= 0 && (pidStr.length() - lastDash - 1) >= 8) {
      // take the part after last '-' (8 chars)
      idLine += pidStr.substring(lastDash + 1);
    } else {
      // fallback: show full prediction_id
      idLine += pidStr;
    }
  } else {
    idLine += "-";
  }

  // ----- OLED: 3 LINES -----
  // Line 1: Patient - NORMAL / NOT NORMAL
  String line1 = isNormal ? "Patient: NORMAL" : "Patient: NOT NORMAL";

  // Show summary on screen (no disease list now)
  oledPrint(line1, dateLine, idLine);

  // ----- LED / BUZZER LOGIC (same spirit as before) -----
  if (isNormal) {
    Serial.println("All diseases false -> patient normal");
    // Green LED ON (no auto timeout; stays until next cycle)
    digitalWrite(LED_GREEN, HIGH);
    digitalWrite(LED_RED, LOW);
    digitalWrite(BUZZER_PIN, LOW);
  } else {
    Serial.println("Some disease detected");
    // Red LED + buzzer pattern (as before)
    digitalWrite(LED_RED, HIGH);

    // buzzer + red for about 7–8 seconds
    for (int i = 0; i < 15; i++) {
      digitalWrite(BUZZER_PIN, HIGH);
      delay(250);
      digitalWrite(BUZZER_PIN, LOW);
      delay(250);
    }

    digitalWrite(LED_RED, LOW);
  }

  // After showing result, wait for user to press button to go home
  awaitAck = true;
}


// ------------ Button logic -------------
bool buttonPressed() {
  return digitalRead(BTN_PIN) == LOW;
}

// ==================================== SETUP / LOOP ====================================
void setup() {
  Serial.begin(115200);
  delay(1000);

  pinMode(ECG_PIN, INPUT);
  pinMode(LO_POS_PIN, INPUT);
  pinMode(LO_NEG_PIN, INPUT);

  pinMode(BTN_PIN, INPUT_PULLUP);
  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(LED_YELLOW, OUTPUT);
  pinMode(LED_GREEN, OUTPUT);
  pinMode(LED_RED, OUTPUT);

  // idle state: all LEDs ON to indicate powered
  digitalWrite(BUZZER_PIN, LOW);
  digitalWrite(LED_GREEN, HIGH);
  digitalWrite(LED_RED, HIGH);
  digitalWrite(LED_YELLOW, HIGH);

  // OLED init
  u8g2.begin();
  oledPrint("ECGenius", "Booting...");

  connectWiFi();
  oledPrint("Welcome to ECGenius", "Press button to start");
}

void loop() {
  // Idle / other states only when not actively diagnosing
  if (!diagnosing) {

    // ===== NEW: waiting for user to acknowledge result screen =====
    if (awaitAck) {
      // Do NOT auto-return to home; wait for button
      if (buttonPressed()) {
        // simple debounce
        delay(50);
        if (buttonPressed()) {
          Serial.println("Button pressed: returning to home screen");
          awaitAck = false;

          // idle state: all LEDs ON to indicate powered
          digitalWrite(BUZZER_PIN, LOW);
          digitalWrite(LED_GREEN, HIGH);
          digitalWrite(LED_RED, HIGH);
          digitalWrite(LED_YELLOW, HIGH);

          oledPrint("Welcome to ECGenius", "Press button to start");
        }
      }
      return;  // stay in this "ack" state
    }

    // ===== NORMAL HOME SCREEN BEHAVIOUR (unchanged) =====
    // Idle: all LEDs ON if not diagnosing and not waiting for ack
    digitalWrite(LED_GREEN, HIGH);
    digitalWrite(LED_RED, HIGH);
    digitalWrite(LED_YELLOW, HIGH);

    if (buttonPressed()) {
      // simple debounce
      delay(50);
      if (buttonPressed()) {
        diagnosing = true;
        Serial.println("Button pressed: starting diagnosis");

        // turn LEDs/buzzer to controlled state
        digitalWrite(LED_GREEN, LOW);
        digitalWrite(LED_RED, LOW);
        digitalWrite(BUZZER_PIN, LOW);

        lastBlink = millis();
        yellowState = true;

        recordECG();
        String json = buildJson();
        String resp = sendToAWS(json);

        // after sending/receiving, solid yellow while interpreting
        digitalWrite(LED_YELLOW, HIGH);

        handlePrediction(resp);

        diagnosing = false;
        // IMPORTANT: We no longer go to home here.
        // The result screen stays until button is pressed (awaitAck == true).
        // oledPrint("Welcome to ECGenius", "Press button to start");  // removed
      }
    }
  }

  // while diagnosing, blinking & buzzer are handled inside recordECG()
}

