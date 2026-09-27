// Optional watchdog variant. Original sketch remains in ../wall_y/.
// Set DEVICE_NAME to Eeva for the second robot; verify its motor pins first.
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

// ===========================
// BLE
// ===========================

const char* DEVICE_NAME = "WALL-Y";

// Random custom UUIDs
#define SERVICE_UUID        "12345678-1234-1234-1234-1234567890ab"
#define COMMAND_CHAR_UUID   "abcdefab-1234-5678-1234-abcdefabcdef"

BLECharacteristic* commandCharacteristic;

bool deviceConnected = false;
SemaphoreHandle_t motorLock;
unsigned long lastMotionCommand = 0;
bool motionActive = false;
const unsigned long COMMAND_TIMEOUT_MS = 500;


// ===========================
// MOTOR PINS
// ===========================

// Left motor
#define AIN1 13
#define AIN2 14

// Right motor
#define BIN1 15
#define BIN2 2


// ===========================
// MOTOR HELPERS
// ===========================

void stopMotors() {
  motionActive = false;

  digitalWrite(AIN1, LOW);
  digitalWrite(AIN2, LOW);

  digitalWrite(BIN1, LOW);
  digitalWrite(BIN2, LOW);

  Serial.println("STOP");
}

void forward() {

  // Left motor forward
  digitalWrite(AIN1, LOW);
  digitalWrite(AIN2, HIGH);

  // Right motor forward (reversed electrically)
  digitalWrite(BIN1, HIGH);
  digitalWrite(BIN2, LOW);

  Serial.println("FORWARD");
}

void backward() {

  // Left motor backward
  digitalWrite(AIN1, HIGH);
  digitalWrite(AIN2, LOW);

  // Right motor backward
  digitalWrite(BIN1, LOW);
  digitalWrite(BIN2, HIGH);

  Serial.println("BACKWARD");
}

void left() {

  // Left wheel backward
  digitalWrite(AIN1, LOW);
  digitalWrite(AIN2, HIGH);

  // Right wheel forward
  digitalWrite(BIN1, LOW);
  digitalWrite(BIN2, HIGH);

  Serial.println("LEFT");
}

void right() {

  // Left wheel forward
  digitalWrite(AIN1, HIGH);
  digitalWrite(AIN2, LOW);

  // Right wheel backward
  digitalWrite(BIN1, HIGH);
  digitalWrite(BIN2, LOW);

  Serial.println("RIGHT");
}


// ===========================
// COMMAND HANDLER
// ===========================

void handleCommand(char command) {

  if (command >= 'a' && command <= 'z') {
    command = command - 32;
  }

  Serial.print("Command received: ");
  Serial.println(command);

  // Callers hold motorLock. H and invalid commands never extend motion.
  if (command == 'F' || command == 'B' || command == 'L' || command == 'R') {
    lastMotionCommand = millis();
    motionActive = true;
  }
  switch (command) {

    case 'F':
      forward();
      break;

    case 'B':
      backward();
      break;

    case 'L':
      left();
      break;

    case 'R':
      right();
      break;

    case 'S':
      stopMotors();
      break;

    case 'H':
      Serial.println("HEALTH: ONLINE");
      break;

    default:
      Serial.println("UNKNOWN COMMAND");
      break;
  }
}


// ===========================
// BLE CALLBACKS
// ===========================

class ServerCallbacks : public BLEServerCallbacks {

  void onConnect(BLEServer* pServer) {

    xSemaphoreTake(motorLock, portMAX_DELAY);
    deviceConnected = true;

    // Make sure robot is stationary when a client connects
    stopMotors();

    xSemaphoreGive(motorLock);
    Serial.println("BLE CLIENT CONNECTED");
  }

  void onDisconnect(BLEServer* pServer) {

    xSemaphoreTake(motorLock, portMAX_DELAY);
    deviceConnected = false;

    Serial.println("BLE CLIENT DISCONNECTED");

    // Safety stop if controller disconnects
    stopMotors();

    xSemaphoreGive(motorLock);

    // Start advertising again
    BLEDevice::startAdvertising();

    Serial.println("Advertising restarted");
  }
};


class CommandCallbacks : public BLECharacteristicCallbacks {

  void onWrite(BLECharacteristic* pCharacteristic) {

    String value = pCharacteristic->getValue();

    if (value.length() == 0) {
      return;
    }

    Serial.print("BLE data received: ");

    for (int i = 0; i < value.length(); i++) {
      Serial.print(value[i]);
    }

    Serial.println();

    char command = value[0];

    xSemaphoreTake(motorLock, portMAX_DELAY);
    if (deviceConnected) handleCommand(command);
    xSemaphoreGive(motorLock);
  }
};


// ===========================
// SETUP
// ===========================

void setup() {

  Serial.begin(115200);


  // Configure motor pins immediately
  pinMode(AIN1, OUTPUT);
  pinMode(AIN2, OUTPUT);
  pinMode(BIN1, OUTPUT);
  pinMode(BIN2, OUTPUT);

  // Force all motor-control pins LOW immediately
  digitalWrite(AIN1, LOW);
  digitalWrite(AIN2, LOW);
  digitalWrite(BIN1, LOW);
  digitalWrite(BIN2, LOW);

  motorLock = xSemaphoreCreateMutex();
  if (motorLock == nullptr) {
    // Do not initialize BLE if synchronization could not be allocated.
    while (true) delay(1000);
  }

  // Always boot stopped
  stopMotors();

  Serial.println();
  Serial.println("Starting BLE...");

  // Start BLE
  BLEDevice::init(DEVICE_NAME);

  // Create server
  BLEServer* server = BLEDevice::createServer();

  server->setCallbacks(
    new ServerCallbacks()
  );

  // Create service
  BLEService* service =
    server->createService(SERVICE_UUID);

  // Create command characteristic
  commandCharacteristic =
    service->createCharacteristic(
      COMMAND_CHAR_UUID,
      BLECharacteristic::PROPERTY_WRITE |
      BLECharacteristic::PROPERTY_WRITE_NR
    );

  commandCharacteristic->setCallbacks(
    new CommandCallbacks()
  );

  // Start service
  service->start();

  // Start advertising
  BLEAdvertising* advertising =
    BLEDevice::getAdvertising();

  advertising->addServiceUUID(
    SERVICE_UUID
  );

  advertising->setScanResponse(true);

  BLEDevice::startAdvertising();

  Serial.println("BLE ready");
  Serial.print("Device name: ");
  Serial.println(DEVICE_NAME);

  Serial.println();
  Serial.println("Commands:");
  Serial.println("F = Forward");
  Serial.println("B = Backward");
  Serial.println("L = Left");
  Serial.println("R = Right");
  Serial.println("S = Stop");
  Serial.println("H = Health");
}


// ===========================
// LOOP
// ===========================

void loop() {
  xSemaphoreTake(motorLock, portMAX_DELAY);
  if (!deviceConnected || (motionActive &&
      (unsigned long)(millis() - lastMotionCommand) >= COMMAND_TIMEOUT_MS)) {
    if (motionActive) stopMotors();
    digitalWrite(AIN1, LOW);
    digitalWrite(AIN2, LOW);
    digitalWrite(BIN1, LOW);
    digitalWrite(BIN2, LOW);
  }
  xSemaphoreGive(motorLock);
  delay(10);
}
