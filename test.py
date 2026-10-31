import subprocess
import re
import time
import sys

POLL_TIME = 0.05

MOVE_THRESHOLD = 20
LONG_PRESS = 0.6

print("=" * 55)
print("             ADB TOUCH RECORDER")
print("=" * 55)
print()
print("[+] No root required")
print("[+] Screen: 1080 x 2220")
print("[+] Touch phone now...")
print("[+] Ctrl+C to stop")
print()


# ==========================================
# CHECK DEVICE
# ==========================================

def check_adb():

    try:
        result = subprocess.run(
            ["adb", "devices"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5
        )

        output = result.stdout.decode(
            "utf-8",
            errors="replace"
        )

        if not any("\tdevice" in x for x in output.splitlines()):
            print("[!] Khong tim thay dien thoai.")
            sys.exit(1)

        print("[+] ADB device OK")
        print()

    except FileNotFoundError:
        print("[!] Khong tim thay adb.exe.")
        sys.exit(1)


check_adb()


# ==========================================
# GET DUMPSYS
# ==========================================

def get_input_dump():

    try:

        result = subprocess.run(
            [
                "adb",
                "shell",
                "dumpsys",
                "input"
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=3
        )

        return result.stdout.decode(
            "utf-8",
            errors="replace"
        )

    except Exception:
        return ""


# ==========================================
# PARSE MOTION EVENTS
# ==========================================

def parse_events(text):

    if not text:
        return []

    events = []

    pattern = re.compile(
        r"MotionEvent\("
        r".*?"
        r"action=(DOWN|MOVE|UP|CANCEL)"
        r".*?"
        r"pointers=\[(.*?)\]"
        r".*?"
        r"age=([0-9.]+)ms",
        re.DOTALL
    )

    for m in pattern.finditer(text):

        action = m.group(1)
        pointer_data = m.group(2)
        age_ms = float(m.group(3))

        coords = re.findall(
            r"\d+:\s*\(\s*([0-9.]+)\s*,\s*([0-9.]+)\s*\)",
            pointer_data
        )

        if not coords:
            continue

        points = tuple(
            (round(float(x)), round(float(y)))
            for x, y in coords
        )

        events.append({
            "action": action,
            "points": points,
            "age": age_ms
        })

    return events


# ==========================================
# TOUCH STATE
# ==========================================

touching = False

start_x = None
start_y = None

last_x = None
last_y = None

down_time = None


# ==========================================
# PROCESS EVENT
# ==========================================

def process_event(action, points, event_time):

    global touching
    global start_x
    global start_y
    global last_x
    global last_y
    global down_time

    if not points:
        return

    x, y = points[0]

    # --------------------------------------
    # DOWN
    # --------------------------------------

    if action == "DOWN":

        touching = True

        start_x = x
        start_y = y

        last_x = x
        last_y = y

        down_time = event_time

        return

    # --------------------------------------
    # MOVE
    # --------------------------------------

    if action == "MOVE":

        if touching:

            last_x = x
            last_y = y

        return

    # --------------------------------------
    # UP
    # --------------------------------------

    if action in ("UP", "CANCEL"):

        if not touching:
            return

        end_x = last_x if last_x is not None else start_x
        end_y = last_y if last_y is not None else start_y

        duration = event_time - down_time

        if duration < 0:
            duration = 0

        dx = end_x - start_x
        dy = end_y - start_y

        distance = (dx * dx + dy * dy) ** 0.5

        # ----------------------------------
        # TAP
        # ----------------------------------

        if distance <= MOVE_THRESHOLD:

            if duration >= LONG_PRESS:

                ms = max(
                    1,
                    round(duration * 1000)
                )

                print(
                    f"adb shell input swipe "
                    f"{start_x} {start_y} "
                    f"{start_x} {start_y} {ms}",
                    flush=True
                )

            else:

                print(
                    f"adb shell input tap "
                    f"{start_x} {start_y}",
                    flush=True
                )

        # ----------------------------------
        # SWIPE
        # ----------------------------------

        else:

            ms = max(
                1,
                round(duration * 1000)
            )

            print(
                f"adb shell input swipe "
                f"{start_x} {start_y} "
                f"{end_x} {end_y} {ms}",
                flush=True
            )

        # ----------------------------------
        # RESET
        # ----------------------------------

        touching = False

        start_x = None
        start_y = None

        last_x = None
        last_y = None

        down_time = None


# ==========================================
# MAIN
# ==========================================

# Thời điểm event cuối cùng đã xử lý
last_event_time = 0.0

# Lần đầu chạy: không replay event cũ
first_run = True


try:

    while True:

        dump_time = time.monotonic()

        text = get_input_dump()

        events = parse_events(text)

        if events:

            parsed = []

            for event in events:

                # age = thời gian từ event tới lúc dumpsys chạy
                #
                # event_time ≈ hiện tại - age

                event_time = (
                    dump_time -
                    event["age"] / 1000.0
                )

                parsed.append(
                    (
                        event_time,
                        event["action"],
                        event["points"]
                    )
                )

            # Sắp xếp event theo thời gian
            parsed.sort(key=lambda x: x[0])

            # ----------------------------------
            # LẦN ĐẦU:
            # bỏ toàn bộ event cũ
            # ----------------------------------

            if first_run:

                last_event_time = parsed[-1][0]

                first_run = False

            else:

                for event_time, action, points in parsed:

                    # Chỉ xử lý event mới
                    if event_time <= last_event_time:
                        continue

                    process_event(
                        action,
                        points,
                        event_time
                    )

                    last_event_time = event_time

        time.sleep(POLL_TIME)


except KeyboardInterrupt:

    print()
    print("[+] Recorder stopped.")