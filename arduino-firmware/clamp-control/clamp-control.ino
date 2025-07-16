// Fx29 Force Control Module
// Copyright (c) 2025 Stijn Slebos, Thijs Bieling, Plense Technologies
// Licensed under the MIT License.
// This software includes code originally developed by Plense Technologies.
// If used or modified in derived works, this notice must remain in the file header,
// unless explicit permission is granted by the repository owner to remove or alter it.

// Arduino sketch to control a stepper-actuated force application using the FX29 load cell.
// Commands via serial (MOVETOFORCE) allow precise positioning based on a force target.
// Endstop logic ensures mechanical safety. Motor speed adapts based on force error.

#define STEP_PIN 6
#define DIR_PIN 7
#define MS1_PIN 3
#define MS2_PIN 4
#define MS3_PIN 5
#define KILLSTOP 8
#define ENDSTOP 9
#define ENABLE_PIN 2
#define FX29_POWER_PIN 10

#define CONVERSION_DELAY_MS 3

#include <Wire.h>
#define FX29_ADDR 0x28
#define MAXFORCE 15

#define MOTORSLOW 50
#define MOTORMID 200
#define MOTORFAST 500

#include <AccelStepper.h>
AccelStepper stepper(AccelStepper::DRIVER, STEP_PIN, DIR_PIN);

String inputBuffer = "";

bool executeflag = false;
bool errorflag = false;

float forceSetpoint = 5;
int timedelaySeconds = 1;

// Resets the FX29 sensor by cycling power
int resetFX29() {
  Serial.println("L#RST");
  digitalWrite(FX29_POWER_PIN, LOW);
  delay(100);
  digitalWrite(FX29_POWER_PIN, HIGH);
  delay(100);
  Wire.beginTransmission(FX29_ADDR);
  if (Wire.endTransmission() != 0) return -2;
  delay(CONVERSION_DELAY_MS);
  return 1;
}

// Reads raw force sensor value from FX29
int readForceFromSensor() {
  Wire.requestFrom(FX29_ADDR, 2);
  delay(CONVERSION_DELAY_MS);
  unsigned long startTime = millis();
  while (Wire.available() < 2) {
    if (millis() - startTime > 10) return -3;
  }
  uint8_t msb = Wire.read();
  uint8_t lsb = Wire.read();
  return ((msb & 0x3F) << 8) | lsb;
}

// Converts raw FX29 value to Newtons
float convertToNewton(int raw) {
  return 0.00308 * (raw - 850);
}

// Performs robust force read with retries and sensor resets
float readForce() {
  const int maxRetries = 5;
  const int maxResetIterations = 2;
  for (int iteration = 0; iteration <= maxResetIterations; iteration++){
    for (int attempt = 0; attempt <= maxRetries; attempt++) {
      int raw = readForceFromSensor();
      if (raw > 0 && raw < 16383) return convertToNewton(raw);
    }
    resetFX29();
  }
  Serial.println("E#FER");
  errorflag = true;
  return -1;
}

// Returns true if digital input pin is pulled LOW
bool endstopReached(int pin){
  return (digitalRead(pin) == LOW);
}

// Outputs force and position log over serial
void serialForcePositionLog(float currentForce, int currentPosition){
  Serial.print("F"); Serial.print(currentForce, 3); Serial.print(" S"); Serial.println(currentPosition);
}

// Configures motor driver for full-step mode
void setMicrostepping() {
  digitalWrite(MS1_PIN, LOW);
  digitalWrite(MS2_PIN, LOW);
  digitalWrite(MS3_PIN, LOW);
}

// Calculates error between target and current force
float getForceError(float targetForce, float currentForce) {
  return targetForce - currentForce;
}

void enableMotor(){ digitalWrite(ENABLE_PIN, LOW); }
void disableMotor(){ digitalWrite(ENABLE_PIN, HIGH); }

// Adjusts motor speed based on force error magnitude
void updateCurrentSpeedOnError(float forceError){
  if (abs(forceError) > 3.0) stepper.setSpeed(-1*MOTORMID);
  else stepper.setSpeed(-1*MOTORSLOW);
}

// Main loop to move actuator until target force is reached or a stop condition is hit
void moveToPosition(float targetForce) {
  enableMotor();
  errorflag = false;
  float currentForce = readForce();
  unsigned long previousTime = 0;
  const unsigned long interval = 10;
  float forceError = 10;

  while (abs(forceError) > 0.5 && forceError > -1 && timedelaySeconds >= 0) {
    if (endstopReached(ENDSTOP) || endstopReached(KILLSTOP) || currentForce > MAXFORCE || errorflag) {
      timedelaySeconds = -1;
    }
    unsigned long currentTime = millis();
    if (currentTime - previousTime >= interval) {
      previousTime = currentTime;
      currentForce = readForce();
      int currentPosition = stepper.currentPosition();
      forceError = getForceError(targetForce, currentForce);
      updateCurrentSpeedOnError(forceError);
      serialForcePositionLog(currentForce, currentPosition);
    }
    stepper.runSpeed();
  }

  if (timedelaySeconds < 0) {
    Serial.println("E#STP");
    delay(1000);
  }
  disableMotor();
}

// Maintains position and logs force for a given delay
void waitOnPosition(int timedelayms) {
  unsigned long start = millis();
  float currentForce = 0;
  while (millis() - start < timedelayms) {
    if (! errorflag) currentForce = readForce();
    int currentPosition = stepper.currentPosition();
    serialForcePositionLog(currentForce, currentPosition);
    delay(10);
  }
}

// Reads and parses serial input commands
String handleSerialInput() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (inputBuffer.length() > 0) {
        String result = parseCommand(inputBuffer);
        inputBuffer = "";
        return result;
      }
    } else {
      inputBuffer += c;
    }
  }
  return "";
}

// Parses and executes the MOVETOFORCE serial command
String parseCommand(String cmd) {
  cmd.trim();
  if (cmd.startsWith("MOVETOFORCE")) {
    int idx1 = cmd.indexOf(' ');
    int idx2 = cmd.indexOf(' ', idx1 + 1);
    if (idx1 > 0 && idx2 > idx1) {
      forceSetpoint = cmd.substring(idx1 + 1, idx2).toFloat();
      timedelaySeconds = cmd.substring(idx2 + 1).toInt();
      executeflag = true;
      return "L#SST";
    }
  }
  return "L#SER";
}

// Moves motor to endstop and resets position to zero
void homeSequence() {
  enableMotor();
  stepper.setSpeed(MOTORFAST);
  unsigned long previousTime = 0;
  const unsigned long interval = 10;
  float currentForce = 0;

  while (!endstopReached(ENDSTOP) && !endstopReached(KILLSTOP)) {
    unsigned long currentTime = millis();
    if (currentTime - previousTime >= interval) {
      previousTime = currentTime;
      if (! errorflag) currentForce = readForce();
      int currentPosition = stepper.currentPosition();
      serialForcePositionLog(currentForce, currentPosition);
    }
    stepper.runSpeed();
  }

  stepper.setCurrentPosition(0);
  stepper.moveTo(-200);
  while (stepper.distanceToGo() != 0) stepper.run();
  executeflag = false;
  disableMotor();
}

// System initialization
void setup() {
  stepper.setMaxSpeed(800.0);
  stepper.setAcceleration(1000.0);
  stepper.setCurrentPosition(0);

  pinMode(MS1_PIN, OUTPUT);
  pinMode(MS2_PIN, OUTPUT);
  pinMode(MS3_PIN, OUTPUT);
  pinMode(KILLSTOP, INPUT_PULLUP);
  pinMode(ENDSTOP, INPUT_PULLUP);
  pinMode(ENABLE_PIN, OUTPUT);
  pinMode(FX29_POWER_PIN, OUTPUT);

  Wire.begin();
  Serial.begin(115200);

  setMicrostepping();
  disableMotor();
  Serial.print("L#INI");
  resetFX29();
  delay(100);
  Serial.println("L#STU");
  Serial.println(endstopReached(ENDSTOP));
  Serial.println(endstopReached(KILLSTOP));
  delay(100);
  Serial.println(endstopReached(ENDSTOP));
  Serial.println(endstopReached(KILLSTOP));
  homeSequence();
}

// Main loop that waits for serial input or executes movement
void loop() {
  if (! executeflag) {
    String result = handleSerialInput();
    if (result.length() > 0) Serial.println(result);
  }
  if (executeflag) {
    moveToPosition(forceSetpoint);
    if (timedelaySeconds > 0) waitOnPosition(timedelaySeconds * 1000);
    homeSequence();
  }
}
