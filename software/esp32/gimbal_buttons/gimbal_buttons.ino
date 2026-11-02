// ESP32 Dual-Servo + 4 Buttons (MG90S)
// Blue axis:  GPIO 32
// Green axis: GPIO 33
// Buttons: G18 (+Blue), G19 (-Blue), G25 (+Green), G26 (-Green)

#include <ESP32Servo.h>
#include <math.h>

//////////////////// Pins ////////////////////
const int SERVO_BLUE_PIN  = 32;  // Blue axis servo
const int SERVO_GREEN_PIN = 33;  // Green axis servo

const int BTN_BLUE_PLUS   = 18;  // +1° Blue
const int BTN_BLUE_MINUS  = 19;  // -1° Blue
const int BTN_GREEN_PLUS  = 25;  // +1° Green
const int BTN_GREEN_MINUS = 26;  // -1° Green

const int BTN_GAMESTART   = 12;  // demonstration begin
const int BTN_GAMEEND     = 14;  // demonstration end

//////////////////// Servo setup ////////////////////
// MG90S works well at 50 Hz, ~500–2400 µs pulse range
const int SERVO_FREQ_HZ = 50;
const int SERVO_MIN_US  = 500;    // broaden if needed, e.g., 500–2400
const int SERVO_MAX_US  = 2400;

//////////////////// Angles ////////////////////
const int ANGLE_MIN = 0;
const int ANGLE_MAX = 180;

// Game script targets these:
const int GREEN_START = 5;    // green starts right end (game start pose)
const int GREEN_END   = 80;   // green "up" position  (constrained)
const int BLUE_START  = 160;  // blue "game" start
const int BLUE_END    = 80;   // blue "tilt" position

// Boot pose:
const int BLUE_BOOT  = 140;   // when system powers up
const int GREEN_BOOT = 5;     // when system powers up

// Current angles (boot pose on startup)
int angleBlue  = BLUE_BOOT;
int angleGreen = GREEN_BOOT;

//////////////////// Debounce ////////////////////
const unsigned long DEBOUNCE_MS   = 8;
const int           STEP_DELAY_MS = 5;  // smooth-move delay

struct Button {
  int pin;
  bool lastStable;            // last debounced state
  bool lastRaw;               // last raw read
  unsigned long lastChangeMs; // last time raw changed
};

Button btnBluePlus   { BTN_BLUE_PLUS,   HIGH, HIGH, 0 };
Button btnBlueMinus  { BTN_BLUE_MINUS,  HIGH, HIGH, 0 };
Button btnGreenPlus  { BTN_GREEN_PLUS,  HIGH, HIGH, 0 };
Button btnGreenMinus { BTN_GREEN_MINUS, HIGH, HIGH, 0 };
Button btnGameStart  { BTN_GAMESTART,   HIGH, HIGH, 0 };
Button btnGameEnd    { BTN_GAMEEND,     HIGH, HIGH, 0 };

Servo servoBlue;
Servo servoGreen;

bool abortGame = false;

bool debounce(Button &b) {
  bool raw = digitalRead(b.pin);
  unsigned long now = millis();
  if (raw != b.lastRaw) {
    b.lastRaw = raw;
    b.lastChangeMs = now;
  }
  if ((now - b.lastChangeMs) > DEBOUNCE_MS && raw != b.lastStable) {
    b.lastStable = raw;
    return true; // state changed (debounced)
  }
  return false;  // no debounced change
}

void attachServos() {
  // Allocate PWM channels automatically
  servoBlue.setPeriodHertz(SERVO_FREQ_HZ);
  servoGreen.setPeriodHertz(SERVO_FREQ_HZ);

  servoBlue.attach(SERVO_BLUE_PIN, SERVO_MIN_US, SERVO_MAX_US);
  servoGreen.attach(SERVO_GREEN_PIN, SERVO_MIN_US, SERVO_MAX_US);

  // On boot, go to boot pose
  servoBlue.write(angleBlue);
  servoGreen.write(angleGreen);
}

void printAngles() {
  Serial.print(F("Blue="));   Serial.print(angleBlue);
  Serial.print(F("°, Green=")); Serial.print(angleGreen);
  Serial.println(F("°"));
}

inline void checkAbortButton() {
  if (digitalRead(BTN_GAMEEND) == LOW) {
    if (!abortGame) {
      Serial.println(F("Game abort requested"));
    }
    abortGame = true;
  }
}

// Clamp GREEN angle based on current BLUE angle (for game)
int clampGreenForCurrentBlue(int desiredGreen) {
  // When blue at ~160 side: green allowed 5–80
  if (angleBlue >= 120) { // closer to 160
    if (desiredGreen < 5)  desiredGreen = 5;
    if (desiredGreen > 80) desiredGreen = 80;
  }
  // When blue at ~80 side: green allowed 10–70
  else { // closer to 80
    if (desiredGreen < 10) desiredGreen = 10;
    if (desiredGreen > 70) desiredGreen = 70;
  }
  return desiredGreen;
}

// Smoothly move ONE servo (generic) from its current angle to target
void moveServoSmooth(Servo &s, int &currentAngle, int targetAngle) {
  targetAngle = constrain(targetAngle, ANGLE_MIN, ANGLE_MAX);
  if (currentAngle == targetAngle) return;

  int step = (currentAngle < targetAngle) ? 1 : -1;
  while (currentAngle != targetAngle && !abortGame) {
    checkAbortButton();
    if (abortGame) break;

    currentAngle += step;
    s.write(currentAngle);
    delay(STEP_DELAY_MS);
  }
}

// Smoothly move GREEN with constraints based on BLUE position
void moveGreenSmoothGame(int targetAngle) {
  targetAngle = clampGreenForCurrentBlue(targetAngle);
  if (angleGreen == targetAngle) return;

  int step = (angleGreen < targetAngle) ? 1 : -1;
  while (angleGreen != targetAngle && !abortGame) {
    checkAbortButton();
    if (abortGame) break;

    angleGreen += step;
    angleGreen = clampGreenForCurrentBlue(angleGreen);
    servoGreen.write(angleGreen);
    delay(STEP_DELAY_MS);
  }
}

// Smoothly move BOTH servos so they start & end at the same time
// Green is constrained based on BLUE during motion
void syncMoveServos(int greenTarget, int blueTarget) {
  greenTarget = clampGreenForCurrentBlue(greenTarget);
  blueTarget  = constrain(blueTarget, ANGLE_MIN, ANGLE_MAX);

  int startGreen = angleGreen;
  int startBlue  = angleBlue;

  int deltaGreen = greenTarget - startGreen;
  int deltaBlue  = blueTarget  - startBlue;

  int steps = max(abs(deltaGreen), abs(deltaBlue));
  if (steps == 0) return;

  for (int i = 1; i <= steps && !abortGame; ++i) {
    checkAbortButton();
    if (abortGame) break;

    float frac = (float)i / (float)steps;

    int newBlue  = (int)lroundf(startBlue  + deltaBlue  * frac);
    int rawGreen = (int)lroundf(startGreen + deltaGreen * frac);
    angleBlue  = newBlue;
    angleGreen = clampGreenForCurrentBlue(rawGreen);

    servoBlue.write(angleBlue);
    servoGreen.write(angleGreen);

    delay(STEP_DELAY_MS);
  }
}

// One full game cycle with constraints
void runGameCycle() {
  // Move from wherever we are to game start pose (with constraints)
  moveGreenSmoothGame(GREEN_START);
  if (abortGame) return;
  moveServoSmooth(servoBlue, angleBlue, BLUE_START);  // green is 5 here
  if (abortGame) return;

  // 1. green alone (constrained)
  moveGreenSmoothGame(GREEN_END);
  if (abortGame) return;
  moveGreenSmoothGame(GREEN_START);
  if (abortGame) return;

  // 2. blue alone:
  // when green at 5 or 80, blue can only go 160 or 80 the other side
  // -> jump directly between 160 and 80 (no sweep at extremes)
  if (!abortGame) {
    checkAbortButton();
    if (abortGame) return;
    angleBlue = BLUE_END;
    servoBlue.write(angleBlue);
    delay(300);
  }
  if (!abortGame) {
    checkAbortButton();
    if (abortGame) return;
    angleBlue = BLUE_START;
    servoBlue.write(angleBlue);
    delay(300);
  }

  // 3. both together up (constrained ranges)
  syncMoveServos(GREEN_END, BLUE_END);
  if (abortGame) return;

  // 4. both together back
  syncMoveServos(GREEN_START, BLUE_START);
  if (abortGame) return;
}

// Runs indefinitely until STOP (BTN_GAMEEND) is pressed
void game() {
  Serial.println(F("Game loop start"));
  abortGame = false;

  while (!abortGame) {
    runGameCycle();
    checkAbortButton();  // quick check between cycles
  }

  Serial.println(F("Game loop stopped"));
  printAngles();
}

void setup() {
  Serial.begin(115200);
  delay(200);

  pinMode(BTN_BLUE_PLUS,   INPUT_PULLUP);
  pinMode(BTN_BLUE_MINUS,  INPUT_PULLUP);
  pinMode(BTN_GREEN_PLUS,  INPUT_PULLUP);
  pinMode(BTN_GREEN_MINUS, INPUT_PULLUP);
  pinMode(BTN_GAMESTART,   INPUT_PULLUP);
  pinMode(BTN_GAMEEND,     INPUT_PULLUP);

  attachServos();

  Serial.println(F("Ready. Buttons: 18=+Blue, 19=-Blue, 25=+Green, 26=-Green, 12=GameStart, 14=GameEnd"));
  printAngles();
}

void loop() {
  bool changed = false;
  const int increment = 10;   // manual adjustment step

  // START game (active LOW)
  if (debounce(btnGameStart) && btnGameStart.lastStable == LOW) {
    abortGame = false;
    game();  // blocks until GAMEEND pressed
  }

  // Manual control only when not in game
  if (!abortGame) {
    // Check debounced edges (active LOW => press is LOW)
    if (debounce(btnBluePlus) && btnBluePlus.lastStable == LOW) {
      angleBlue = constrain(angleBlue + increment, ANGLE_MIN, ANGLE_MAX);
      servoBlue.write(angleBlue);
      changed = true;
    }
    if (debounce(btnBlueMinus) && btnBlueMinus.lastStable == LOW) {
      angleBlue = constrain(angleBlue - increment, ANGLE_MIN, ANGLE_MAX);
      servoBlue.write(angleBlue);
      changed = true;
    }
    if (debounce(btnGreenPlus) && btnGreenPlus.lastStable == LOW) {
      angleGreen = constrain(angleGreen + increment, ANGLE_MIN, ANGLE_MAX);
      servoGreen.write(angleGreen);
      changed = true;
    }
    if (debounce(btnGreenMinus) && btnGreenMinus.lastStable == LOW) {
      angleGreen = constrain(angleGreen - increment, ANGLE_MIN, ANGLE_MAX);
      servoGreen.write(angleGreen);
      changed = true;
    }
  }

  if (changed) {
    printAngles();
  }
}
