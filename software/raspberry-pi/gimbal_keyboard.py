import pigpio
import time
import math
import threading
import curses

#################### Pins ####################
SERVO_BLUE_PIN  = 12   # BCM
SERVO_GREEN_PIN = 13   # BCM

#################### Servo setup ####################
SERVO_FREQ_HZ = 50
SERVO_MIN_US  = 500
SERVO_MAX_US  = 2400

#################### Angles ####################
ANGLE_MIN = 0
ANGLE_MAX = 180

GREEN_START = 5
GREEN_END   = 80
BLUE_START  = 160
BLUE_END    = 80

BLUE_BOOT  = 50
GREEN_BOOT = 140

angle_blue  = BLUE_BOOT
angle_green = GREEN_BOOT

STEP_DELAY = 0.005  # 5 ms

# Game state
abort_game   = False
game_running = False
game_thread  = None

#################### pigpio ####################
pi = pigpio.pi()
if not pi.connected:
    print("ERROR: pigpio not running (did you `sudo systemctl start pigpiod`?)")
    raise SystemExit

pi.set_PWM_frequency(SERVO_BLUE_PIN, SERVO_FREQ_HZ)
pi.set_PWM_frequency(SERVO_GREEN_PIN, SERVO_FREQ_HZ)

#################### Servo helpers ####################
def angle_to_us(angle):
    angle = max(ANGLE_MIN, min(ANGLE_MAX, angle))
    return int(SERVO_MIN_US + (angle / 180.0) * (SERVO_MAX_US - SERVO_MIN_US))

def write_servo(pin, angle):
    pulse = angle_to_us(angle)
    pi.set_servo_pulsewidth(pin, pulse)

def attach_servos():
    global angle_blue, angle_green
    write_servo(SERVO_BLUE_PIN,  angle_blue)
    write_servo(SERVO_GREEN_PIN, angle_green)

def print_angles(stdscr=None):
    msg = f"Blue={angle_blue}°, Green={angle_green}°"
    if stdscr is None:
        print(msg)
    else:
        stdscr.addstr(1, 0, " " * 40)
        stdscr.addstr(1, 0, msg)
        stdscr.refresh()

#################### Constraints & motion ####################
def clamp_green(desired):
    global angle_blue
    if angle_blue >= 120:
        return max(5, min(80, desired))
    else:
        return max(10, min(70, desired))

def move_smooth(pin, ref_name, target):
    global angle_blue, angle_green, abort_game

    target = max(ANGLE_MIN, min(ANGLE_MAX, target))
    current = angle_blue if ref_name == "blue" else angle_green

    if current == target:
        return

    step = 1 if current < target else -1

    while current != target and not abort_game:
        current += step

        if ref_name == "green":
            current = clamp_green(current)

        write_servo(pin, current)

        if ref_name == "blue":
            angle_blue = current
        else:
            angle_green = current

        time.sleep(STEP_DELAY)

def move_green_smooth(target):
    move_smooth(SERVO_GREEN_PIN, "green", clamp_green(target))

def sync_move(green_target, blue_target):
    global angle_blue, angle_green, abort_game

    green_target = clamp_green(green_target)
    blue_target  = max(ANGLE_MIN, min(ANGLE_MAX, blue_target))

    start_g = angle_green
    start_b = angle_blue

    steps = max(abs(green_target - start_g), abs(blue_target - start_b))
    if steps == 0:
        return

    for i in range(1, steps + 1):
        if abort_game:
            return

        frac = i / steps

        new_blue = int(round(start_b + (blue_target - start_b) * frac))
        new_green_raw = int(round(start_g + (green_target - start_g) * frac))
        new_green = clamp_green(new_green_raw)

        angle_blue = new_blue
        angle_green = new_green

        write_servo(SERVO_BLUE_PIN, new_blue)
        write_servo(SERVO_GREEN_PIN, new_green)

        time.sleep(STEP_DELAY)

#################### Game logic ####################
def run_game_cycle():
    global abort_game

    move_green_smooth(GREEN_START)
    if abort_game: return

    move_smooth(SERVO_BLUE_PIN, "blue", BLUE_START)
    if abort_game: return

    move_green_smooth(GREEN_END)
    if abort_game: return

    move_green_smooth(GREEN_START)
    if abort_game: return

    # Blue alone: jump between 160 and 80
    if not abort_game:
        write_servo(SERVO_BLUE_PIN, BLUE_END)
        time.sleep(0.3)
    if not abort_game:
        write_servo(SERVO_BLUE_PIN, BLUE_START)
        time.sleep(0.3)

    sync_move(GREEN_END, BLUE_END)
    if abort_game: return

    sync_move(GREEN_START, BLUE_START)
    if abort_game: return

def game_loop():
    global abort_game, game_running
    while game_running and not abort_game:
        run_game_cycle()
    game_running = False  # ensure flag sync

#################### Keyboard “virtual buttons” ####################
def press_blue_plus(step=10):
    global angle_blue
    angle_blue = min(ANGLE_MAX, angle_blue + step)
    write_servo(SERVO_BLUE_PIN, angle_blue)

def press_blue_minus(step=10):
    global angle_blue
    angle_blue = max(ANGLE_MIN, angle_blue - step)
    write_servo(SERVO_BLUE_PIN, angle_blue)

def press_green_plus(step=10):
    global angle_green
    angle_green = min(ANGLE_MAX, angle_green + step)
    write_servo(SERVO_GREEN_PIN, angle_green)

def press_green_minus(step=10):
    global angle_green
    angle_green = max(ANGLE_MIN, angle_green - step)
    write_servo(SERVO_GREEN_PIN, angle_green)

def toggle_game(stdscr=None):
    global game_running, abort_game, game_thread
    if not game_running:
        abort_game = False
        game_running = True
        game_thread = threading.Thread(target=game_loop, daemon=True)
        game_thread.start()
        if stdscr: stdscr.addstr(3, 0, "Game: RUNNING      ")
    else:
        abort_game = True
        game_running = False
        if stdscr: stdscr.addstr(3, 0, "Game: STOP REQUEST ")
    if stdscr: stdscr.refresh()

#################### Main keyboard loop (curses) ####################
HELP_TEXT = "Keys: a/d=Blue -/+, w/s=Green +/- , g=toggle game, q=quit"

def main_curses(stdscr):
    curses.curs_set(0)   # hide cursor
    stdscr.nodelay(True) # non-blocking getch
    stdscr.clear()
    stdscr.addstr(0, 0, HELP_TEXT)
    stdscr.refresh()

    print_angles(stdscr)

    while True:
        try:
            c = stdscr.getch()
        except KeyboardInterrupt:
            break

        if c == -1:
            time.sleep(0.01)
            continue

        ch = chr(c) if 0 <= c < 256 else ""

        if ch == 'q':
            stdscr.addstr(4, 0, "Quitting...          ")
            stdscr.refresh()
            break
        elif ch == 'a':
            press_blue_minus()
        elif ch == 'd':
            press_blue_plus()
        elif ch == 'w':
            press_green_plus()
        elif ch == 's':
            press_green_minus()
        elif ch == 'g':
            toggle_game(stdscr)

        print_angles(stdscr)

def main():
    attach_servos()
    print("Servos attached. Use keyboard in the terminal.")
    curses.wrapper(main_curses)

    # cleanup
    global game_running, abort_game
    abort_game = True
    game_running = False
    time.sleep(0.2)
    pi.set_servo_pulsewidth(SERVO_BLUE_PIN, 0)
    pi.set_servo_pulsewidth(SERVO_GREEN_PIN, 0)
    pi.stop()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pi.set_servo_pulsewidth(SERVO_BLUE_PIN, 0)
        pi.set_servo_pulsewidth(SERVO_GREEN_PIN, 0)
        pi.stop()