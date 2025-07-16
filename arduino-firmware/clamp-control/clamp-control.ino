#define STEP_PIN 6
#define DIR_PIN 7
#define MS1_PIN 3
#define MS2_PIN 4
#define MS3_PIN 5
#define KILLSTOP 8
#define ENDSTOP 9
#define ENABLE_PIN 2

#include <Wire.h>
#define FORCE_ADDR 0x28
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

int readForceFromSensor() {
  
  Wire.requestFrom(FORCE_ADDR, 2);

  unsigned long startTime = millis();
  if (Wire.available() < 2){
    Serial.println("I2CTIMEOUT");
    return -1;
  } 

  uint8_t msb = Wire.read();
  uint8_t lsb = Wire.read();

  return ((msb & 0x3F) << 8) | lsb;  // 14-bit output
}

float convertToNewton(int raw) {
  return 0.00308 * (raw - 850);
}

float readForce() {
  const int maxRetries = 2;
  for (int attempt = 0; attempt <= maxRetries; attempt++) {
    int raw = readForceFromSensor();
    if (raw >= 0) {
      return convertToNewton(raw);
    }
  }
  Serial.println("FORCEERROR");
  errorflag = true;
  return -1;
}

bool endstopReached(int pin){
  return (digitalRead(pin) == LOW);
}

void serialForcePositionLog(float currentForce, int currentPosition){
  Serial.print("F"); Serial.print(currentForce, 3); Serial.print(" S"); Serial.println(currentPosition);
}

void setMicrostepping() {
  digitalWrite(MS1_PIN, LOW);
  digitalWrite(MS2_PIN, LOW);
  digitalWrite(MS3_PIN, LOW); // 1
}

float getForceError(float targetForce, float currentForce) {
  float forceError = targetForce - currentForce;
  return forceError;
}

void enableMotor(){
  digitalWrite(ENABLE_PIN, LOW);
}

void disableMotor(){
    digitalWrite(ENABLE_PIN, HIGH);
}

void updateCurrentSpeedOnError(float forceError){
    if (abs(forceError) > 3.0){
    stepper.setSpeed(-1*MOTORMID);
  } else{
    stepper.setSpeed(-1*MOTORSLOW);
  }
}

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
    Serial.println("FAIL");
    delay(1000);
  }

  disableMotor();
}

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
  return "";  // no result yet
}

String parseCommand(String cmd) {
  cmd.trim();
  if (cmd.startsWith("MOVETOFORCE")) {
    int idx1 = cmd.indexOf(' ');
    int idx2 = cmd.indexOf(' ', idx1 + 1);
    if (idx1 > 0 && idx2 > idx1) {
      forceSetpoint = cmd.substring(idx1 + 1, idx2).toFloat();
      timedelaySeconds = cmd.substring(idx2 + 1).toInt();
      executeflag = true;
      return "START";
    }
  }
  return "ERROR";
}

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

  while (stepper.distanceToGo() != 0) {
    stepper.run();
  }

  
  executeflag = false;
  disableMotor();
}

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

  Wire.begin();
  Serial.begin(9600);

  setMicrostepping();

  disableMotor();

  Serial.println("STARTUP");
  Serial.println(endstopReached(ENDSTOP));
  Serial.println(endstopReached(KILLSTOP));
  delay(100);
  Serial.println(endstopReached(ENDSTOP));
  Serial.println(endstopReached(KILLSTOP));
  homeSequence();
}

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
