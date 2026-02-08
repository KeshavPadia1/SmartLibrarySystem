import board
import displayio
import terminalio
import digitalio
from adafruit_display_text import label
import adafruit_aw9523
import adafruit_miniqr
import time
import espcamera
import qrio
import struct  # <--- NEW: For packing display window coordinates

# --- TESTING CONFIG ---
now_time = time.struct_time((2026, 2, 6, 20, 30, 0, 4, 37, 0))
test_delay_seconds = 17 * 86400

# --- 1. THE DATABASE ---
users_db = {
    "01": {"name": "Amit Sharma", "role": "Student", "password": "1234"},
    "02": {"name": "Priya Verma", "role": "Student", "password": "5678"},
}
books_db = {
    "978-1": {"title": "Python Basics", "total": 5, "available": 5},
    "978-2": {"title": "Adv. Circuits", "total": 3, "available": 3},
    "978-3": {"title": "Data Science", "total": 4, "available": 2},
    "978-4": {"title": "ESP32 Guide", "total": 6, "available": 6},
    "978-5": {"title": "Calculus II", "total": 2, "available": 1}
}
book_keys = list(books_db.keys())
transactions_log = []
borrowings = {}

# --- 2. LOGIC FUNCTIONS ---
def get_timestamp():
    return "{}/{}/{} {}:{:02d}".format(now_time.tm_mday, now_time.tm_mon, now_time.tm_year, now_time.tm_hour, now_time.tm_min)

def wrap_text(text, max_chars=20):
    lines = []
    for line in text.split('\n'):
        while len(line) > max_chars:
            split_idx = line.rfind(' ', 0, max_chars)
            if split_idx == -1: split_idx = max_chars
            lines.append(line[:split_idx])
            line = line[split_idx:].strip()
        lines.append(line)
    return '\n'.join(lines)

def calculate_days(issue_time):
    issue_sec = time.mktime(issue_time)
    now_sec = time.mktime(now_time) + test_delay_seconds
    return (now_sec - issue_sec) // 86400

def issue_book_logic(user_id, isbn):
    if user_id not in users_db: return ("ERROR", "User ID Not Found", 0)
    book = books_db.get(isbn)
    if not book: return ("ERROR", "Book Not Found", 0)
    if book['available'] > 0:
        book['available'] -= 1
        if user_id not in borrowings: borrowings[user_id] = []
        issue_time = now_time
        borrowings[user_id].append({"isbn": isbn, "issue_time": issue_time})
        due_time = time.localtime(time.mktime(issue_time) + 15 * 86400)
        due_str = f"{due_time.tm_mday}/{due_time.tm_mon}/{due_time.tm_year}"
        return ("SUCCESS!", f"Issued: {book['title']}\nReturn by: {due_str}\nRem Copies: {book['available']}", 0)
    else:
        return ("OOPS!", "No copies left\nfor this book.", 0)

def return_book_logic(user_id, isbn):
    book = books_db.get(isbn)
    if not book: return ("ERROR", "Book Not Found", 0)
    if user_id in borrowings:
        for borrowing in borrowings[user_id]:
            if borrowing["isbn"] == isbn:
                days = calculate_days(borrowing["issue_time"])
                delay = days - 15
                fine = max(0, delay) * 15
                book['available'] += 1
                borrowings[user_id].remove(borrowing)
                if not borrowings[user_id]: del borrowings[user_id]
                msg_fine = f"Fine: {fine} Rs" if fine > 0 else "No Fine"
                return ("RETURNED", f"Book: {book['title']}\n{msg_fine}\nNow Available: {book['available']}", fine)
        return ("ERROR", "You don't have\nthis book.", 0)
    else:
        return ("ERROR", "No borrowings.", 0)

# --- 3. CAMERA & QR SETUP ---
print("Initializing Camera...")
cam = None  # <--- CRITICAL FIX: Define cam as None first!
qrdecoder = None
try:
    cam = espcamera.Camera(
        data_pins=board.CAMERA_DATA,
        external_clock_pin=board.CAMERA_XCLK,
        pixel_clock_pin=board.CAMERA_PCLK,
        vsync_pin=board.CAMERA_VSYNC,
        href_pin=board.CAMERA_HREF,
        pixel_format=espcamera.PixelFormat.RGB565,
        frame_size=espcamera.FrameSize.R240X240,
        i2c=board.I2C(),
        external_clock_frequency=20_000_000,
        framebuffer_count=1  # Reduced to 1 to save RAM/Resources
    )
    cam.vflip = True
    cam.hmirror = True
    qrdecoder = qrio.QRDecoder(cam.width, cam.height)
    print("Camera Ready.")
except Exception as e:
    print("Camera Init Failed:", e)
    # We do NOT stop here, we continue so the menu still works!

# --- 4. DISPLAY SETUP ---
display = board.DISPLAY

# Shared Background (Navy Blue for calm and trust)
color_bitmap = displayio.Bitmap(240, 240, 1)
color_palette = displayio.Palette(1)
color_palette[0] = 0x001F3F  # Navy blue background
bg_sprite = displayio.TileGrid(color_bitmap, pixel_shader=color_palette, x=0, y=0)

# --- GROUPS ---
welcome_group = displayio.Group()
greeting_group = displayio.Group()
main_group = displayio.Group()
selection_group = displayio.Group()  # BOOK LIST (Manual fallback)
confirm_group = displayio.Group()
id_group = displayio.Group()
pin_group = displayio.Group()
book_confirm_group = displayio.Group()
qr_group = displayio.Group()
scan_group = displayio.Group()  # NEW: Scanning Overlay

# Add Backgrounds to all
for g in [welcome_group, greeting_group, main_group, selection_group, confirm_group, id_group, pin_group, book_confirm_group, qr_group, scan_group]:
    g.append(displayio.TileGrid(color_bitmap, pixel_shader=color_palette))

# --- WELCOME UI ---
lbl_welcome = label.Label(terminalio.FONT, text="", color=0xFFFFFF, scale=3)  # White text for better contrast
lbl_welcome.anchor_point = (0.5, 0.5); lbl_welcome.anchored_position = (display.width / 2, display.height / 2)
welcome_group.append(lbl_welcome)

# --- GREETING UI ---
lbl_greeting = label.Label(terminalio.FONT, text="", color=0xFFFFFF, scale=3)  # Increased scale to 3 for bigger font, white for contrast
lbl_greeting.anchor_point = (0.5, 0.5); lbl_greeting.anchored_position = (display.width / 2, display.height / 2)
greeting_group.append(lbl_greeting)

# --- MAIN MENU UI ---
COLOR_SELECTED = 0xFFD700  # Gold for selected, warm accent
COLOR_NORMAL = 0xFFFFFF  # White for normal
lbl_opt1 = label.Label(terminalio.FONT, text="> ISSUE BOOK", color=COLOR_SELECTED, scale=2)
lbl_opt1.anchor_point = (0.5, 0.5); lbl_opt1.anchored_position = (display.width / 2, display.height / 2 - 45)
main_group.append(lbl_opt1)
lbl_opt2 = label.Label(terminalio.FONT, text=" RETURN BOOK", color=COLOR_NORMAL, scale=2)
lbl_opt2.anchor_point = (0.5, 0.5); lbl_opt2.anchored_position = (display.width / 2, display.height / 2)
main_group.append(lbl_opt2)
lbl_opt3 = label.Label(terminalio.FONT, text=" LOGOUT", color=COLOR_NORMAL, scale=2)
lbl_opt3.anchor_point = (0.5, 0.5); lbl_opt3.anchored_position = (display.width / 2, display.height / 2 + 45)
main_group.append(lbl_opt3)

# --- SCAN UI ---
lbl_scan_status = label.Label(terminalio.FONT, text="Scanning...", color=0xFFFFFF, scale=2)  # White text
lbl_scan_status.anchor_point = (0.5, 0); lbl_scan_status.anchored_position = (display.width / 2, 10)
scan_group.append(lbl_scan_status)
lbl_scan_instr = label.Label(terminalio.FONT, text="Point at QR\nBTN Left: Manual", color=0xFFFFFF, scale=1)
lbl_scan_instr.anchor_point = (0.5, 1.0); lbl_scan_instr.anchored_position = (display.width / 2, display.height - 10)
scan_group.append(lbl_scan_instr)

# --- SELECTION LIST UI (EXISTING) ---
lbl_list_header = label.Label(terminalio.FONT, text="SELECT BOOK", color=0xFFFFFF, scale=2)  # White text
lbl_list_header.anchor_point = (0.5, 0); lbl_list_header.anchored_position = (display.width / 2, 10)
selection_group.append(lbl_list_header)
book_row_labels = []
start_y = 65
for i in range(5):
    l = label.Label(terminalio.FONT, text="", color=COLOR_NORMAL, scale=2)
    l.anchor_point = (0.0, 0.0); l.anchored_position = (10, start_y + (i * 30))
    book_row_labels.append(l); selection_group.append(l)

# --- CONFIRM/RESULT UI ---
lbl_confirm_header = label.Label(terminalio.FONT, text="", color=0xFFFFFF, scale=3)  # White text
lbl_confirm_header.anchor_point = (0.5, 0.5); lbl_confirm_header.anchored_position = (display.width / 2, 60)
confirm_group.append(lbl_confirm_header)
lbl_confirm_body = label.Label(terminalio.FONT, text="", color=0xFFFFFF, scale=2)
lbl_confirm_body.anchor_point = (0.5, 0.0); lbl_confirm_body.anchored_position = (display.width / 2, 90)
confirm_group.append(lbl_confirm_body)
lbl_back = label.Label(terminalio.FONT, text="Press OK", color=0x888888, scale=1)
lbl_back.anchor_point = (0.5, 1.0); lbl_back.anchored_position = (display.width / 2, display.height - 10)
confirm_group.append(lbl_back)

# --- LOGIN ID UI ---
lbl_id_header = label.Label(terminalio.FONT, text="Enter ID:", color=0xFFFFFF, scale=2)  # White text
lbl_id_header.anchor_point = (0.5, 0); lbl_id_header.anchored_position = (display.width / 2, 20)
id_group.append(lbl_id_header)
id_digits = []
digit_x = [80, 140]
for i in range(2):
    l = label.Label(terminalio.FONT, text="0", color=0xFFFFFF, scale=4)
    l.anchor_point = (0.5, 0.5); l.anchored_position = (digit_x[i], 120)
    id_digits.append(l); id_group.append(l)
lbl_id_cursor = label.Label(terminalio.FONT, text="^", color=0xFFD700, scale=2)  # Gold cursor
lbl_id_cursor.anchor_point = (0.5, 0.5); lbl_id_cursor.anchored_position = (digit_x[0], 160)
id_group.append(lbl_id_cursor)

# --- LOGIN PIN UI ---
lbl_pin_header = label.Label(terminalio.FONT, text="Enter PIN:", color=0xFFFFFF, scale=2)  # White text
lbl_pin_header.anchor_point = (0.5, 0); lbl_pin_header.anchored_position = (display.width / 2, 20)
pin_group.append(lbl_pin_header)
pin_digits = []
pin_x = [60, 100, 140, 180]
for i in range(4):
    l = label.Label(terminalio.FONT, text="0", color=0xFFFFFF, scale=4)
    l.anchor_point = (0.5, 0.5); l.anchored_position = (pin_x[i], 120)
    pin_digits.append(l); pin_group.append(l)
lbl_pin_cursor = label.Label(terminalio.FONT, text="^", color=0xFFD700, scale=2)  # Gold cursor
lbl_pin_cursor.anchor_point = (0.5, 0.5); lbl_pin_cursor.anchored_position = (pin_x[0], 160)
pin_group.append(lbl_pin_cursor)

# --- BOOK CONFIRM UI ---
lbl_book_confirm_header = label.Label(terminalio.FONT, text="", color=0xFFFFFF, scale=2)  # White text
lbl_book_confirm_header.anchor_point = (0.5, 0); lbl_book_confirm_header.anchored_position = (display.width / 2, 20)
book_confirm_group.append(lbl_book_confirm_header)
lbl_yes = label.Label(terminalio.FONT, text="> Yes", color=COLOR_SELECTED, scale=3)
lbl_yes.anchor_point = (0.5, 0.5); lbl_yes.anchored_position = (display.width / 2, display.height / 2 - 30)
book_confirm_group.append(lbl_yes)
lbl_no = label.Label(terminalio.FONT, text=" No", color=COLOR_NORMAL, scale=3)
lbl_no.anchor_point = (0.5, 0.5); lbl_no.anchored_position = (display.width / 2, display.height / 2 + 30)
book_confirm_group.append(lbl_no)

# --- QR DISPLAY GROUP ---
lbl_qr_header = label.Label(terminalio.FONT, text="Scan to Pay", color=0xFFFFFF, scale=2)  # White text
lbl_qr_header.anchor_point = (0.5, 0); lbl_qr_header.anchored_position = (display.width / 2, 10)
qr_group.append(lbl_qr_header)

# --- 5. BUTTON SETUP ---
i2c = board.I2C()
aw = adafruit_aw9523.AW9523(i2c)
btn_up = aw.get_pin(13); btn_up.direction = digitalio.Direction.INPUT
btn_down = aw.get_pin(15); btn_down.direction = digitalio.Direction.INPUT
btn_ok = aw.get_pin(11); btn_ok.direction = digitalio.Direction.INPUT
btn_left = aw.get_pin(12); btn_left.direction = digitalio.Direction.INPUT
btn_right = aw.get_pin(14); btn_right.direction = digitalio.Direction.INPUT

# --- 6. ANIMATION & UPDATE FUNCTIONS ---
def run_welcome_animation():
    display.root_group = welcome_group
    # Full phrase we want to animate
    full_text = "SMART\nLIBRARY\nSYSTEM"
    current_text = ""
    lbl_welcome.text = ""  # Start clear
    
    # Typewriter effect: Add one character at a time
    for char in full_text:
        current_text += char
        lbl_welcome.text = current_text
        time.sleep(0.1)  # Adjust speed of typing here
    
    time.sleep(1.0)  # Pause to let user read it

def update_main_menu_ui(idx):
    lbl_opt1.text = "> ISSUE BOOK" if idx == 0 else " ISSUE BOOK"
    lbl_opt1.color = COLOR_SELECTED if idx == 0 else COLOR_NORMAL
    lbl_opt2.text = "> RETURN BOOK" if idx == 1 else " RETURN BOOK"
    lbl_opt2.color = COLOR_SELECTED if idx == 1 else COLOR_NORMAL
    lbl_opt3.text = "> LOGOUT" if idx == 2 else " LOGOUT"
    lbl_opt3.color = COLOR_SELECTED if idx == 2 else COLOR_NORMAL

def update_book_list_ui(selected_idx):
    for i in range(len(book_row_labels)):
        isbn = book_keys[i]
        title = books_db[isbn]['title'][:11]
        text_str = f"{title} {books_db[isbn]['available']}"
        book_row_labels[i].text = "> " + text_str if i == selected_idx else " " + text_str
        book_row_labels[i].color = COLOR_SELECTED if i == selected_idx else COLOR_NORMAL

def update_book_confirm_ui(idx):
    lbl_yes.text = "> Yes" if idx == 0 else " Yes"
    lbl_yes.color = COLOR_SELECTED if idx == 0 else COLOR_NORMAL
    lbl_no.text = "> No" if idx == 1 else " No"
    lbl_no.color = COLOR_SELECTED if idx == 1 else COLOR_NORMAL

def update_id_cursor():
    lbl_id_cursor.anchored_position = (digit_x[id_pos], 160)

def update_pin_cursor():
    lbl_pin_cursor.anchored_position = (pin_x[pin_pos], 160)

def generate_qr(fine):
    # Same as your existing logic
    upi_id = "library@upi"; name = "Smart Library"
    url = f"upi://pay?pa={upi_id}&pn={name}&am={fine}&cu=INR&tn=Book Fine"
    qr = adafruit_miniqr.QRCode(qr_type=5, error_correct=adafruit_miniqr.L)
    qr.add_data(url.encode())
    qr.make()
    matrix = qr.matrix
    scale = 4; border = 2; width = (matrix.width + 2*border) * scale; height = width
    bitmap = displayio.Bitmap(width, height, 2)
    palette = displayio.Palette(2); palette[0] = 0xFFFFFF; palette[1] = 0x000000
    for x in range(matrix.width):
        for y in range(matrix.height):
            if matrix[x, y]:
                for i in range(scale):
                    for j in range(scale):
                        bitmap[x*scale + border*scale + i, y*scale + border*scale + j] = 1
    tile = displayio.TileGrid(bitmap, pixel_shader=palette, x=(display.width - width) // 2, y=40)
    return tile

def perform_scan():
    """Safely handles camera scanning"""
    # 1. CHECK IF CAMERA EXISTS
    if cam is None:
        print("Error: Camera not initialized")
        lbl_scan_status.text = "Camera Failed!"
        lbl_scan_instr.text = "Hardware Error"
        display.root_group = scan_group
        time.sleep(2.0)
        return None  # Return None so it acts like a cancelled scan

    display.root_group = scan_group
    display.refresh()  # <--- NEW: Render UI overlays once
    display.auto_refresh = False
    display_bus = display.bus

    # <--- NEW: Set up preview window (full width, cropped height to avoid overwriting UI)
    preview_y_start = 40  # Leave top 40px for status label
    preview_height = 160  # 240 - 40 (top) - 40 (bottom)
    preview_y_end = preview_y_start + preview_height - 1

    # Crop frame to match: skip top/bottom rows symmetrically
    row_bytes = 240 * 2  # RGB565: 2 bytes/pixel
    crop_top_rows = (240 - preview_height) // 2  # e.g., 40 rows
    start_byte = crop_top_rows * row_bytes
    crop_bytes = preview_height * row_bytes

    # Set display address window (MIPI DCS commands)
    display_bus.send(0x2A, struct.pack(">HH", 0, 239))  # Columns: full width
    display_bus.send(0x2B, struct.pack(">HH", preview_y_start, preview_y_end))  # Rows: preview area

    found_data = None

    while True:
        try:
            frame = cam.take(1)
            cropped_frame = frame[start_byte : start_byte + crop_bytes]
            display_bus.send(0x2C, cropped_frame)  # <--- CHANGED: Send cropped frame to subregion

            for row in qrdecoder.decode(frame, qrio.PixelPolicy.RGB565_SWAPPED):  # Decode full frame
                payload = row.payload
                try:
                    found_data = payload.decode("utf-8")
                except:
                    found_data = str(payload)
        except Exception as e:
            print("Frame Capture Error:", e)
            break

        if found_data:
            break

        if not btn_left.value:
            break

    display.auto_refresh = True  # <--- NEW: Restore auto refresh
    return found_data

# --- 7. MAIN PROGRAM ---
run_welcome_animation()

# STATES: 3=ID, 4=PIN, 0=Menu, 1=BookSel, 5=BookConf, 2=Result, 7=QR, 6=SCAN
current_state = 3
current_user = ""
current_fine = 0
selected_isbn = ""
id_pos = 0; pin_pos = 0; menu_index = 0; book_index = 0; confirm_index = 0
update_id_cursor(); display.root_group = id_group

while True:

    # --- STATE 3 & 4 (LOGIN) ---
    # (Kept identical to your logic, omitted for brevity in explanation but included in logic)
    if current_state == 3:
        if not btn_left.value and id_pos > 0: id_pos -= 1; update_id_cursor(); time.sleep(0.2)
        if not btn_right.value and id_pos < 1: id_pos += 1; update_id_cursor(); time.sleep(0.2)
        if not btn_up.value: id_digits[id_pos].text = str((int(id_digits[id_pos].text) + 1) % 10); time.sleep(0.2)
        if not btn_down.value: id_digits[id_pos].text = str((int(id_digits[id_pos].text) - 1) % 10); time.sleep(0.2)
        if not btn_ok.value:
            user_id = ''.join(d.text for d in id_digits)
            if user_id in users_db:
                temp_user_id = user_id; pin_pos = 0; update_pin_cursor(); display.root_group = pin_group; current_state = 4
                for d in pin_digits: d.text = '0'
            else:
                lbl_id_header.text = "Invalid ID"; lbl_id_header.color = 0xFF0000; time.sleep(1)
                lbl_id_header.text = "Enter ID:"; lbl_id_header.color = 0xFFFFFF
            time.sleep(0.5)
    elif current_state == 4:
        if not btn_left.value and pin_pos > 0: pin_pos -= 1; update_pin_cursor(); time.sleep(0.2)
        if not btn_right.value and pin_pos < 3: pin_pos += 1; update_pin_cursor(); time.sleep(0.2)
        if not btn_up.value: pin_digits[pin_pos].text = str((int(pin_digits[pin_pos].text) + 1) % 10); time.sleep(0.2)
        if not btn_down.value: pin_digits[pin_pos].text = str((int(pin_digits[pin_pos].text) - 1) % 10); time.sleep(0.2)
        if not btn_ok.value:
            entered = ''.join(d.text for d in pin_digits)
            if entered == users_db[temp_user_id]["password"]:
                current_user = temp_user_id
                lbl_greeting.text = f"Hello\n{users_db[current_user]['name']}"; display.root_group = greeting_group; time.sleep(2)
                menu_index = 0; update_main_menu_ui(0); display.root_group = main_group; current_state = 0
            else:
                lbl_pin_header.text = "Wrong PIN"; lbl_pin_header.color = 0xFF0000; time.sleep(1)
                lbl_pin_header.text = "Enter PIN:"; lbl_pin_header.color = 0xFFFFFF
                for d in pin_digits: d.text = '0'
                pin_pos = 0; update_pin_cursor()
            time.sleep(0.5)

    # --- STATE 0: MAIN MENU ---
    elif current_state == 0:
        if not btn_up.value: menu_index = (menu_index - 1) % 3; update_main_menu_ui(menu_index); time.sleep(0.2)
        if not btn_down.value: menu_index = (menu_index + 1) % 3; update_main_menu_ui(menu_index); time.sleep(0.2)
        if not btn_ok.value:
            if menu_index == 2:  # LOGOUT
                current_user = ""; display.root_group = id_group; current_state = 3
                for d in id_digits: d.text='0'
            else:
                current_mode = "ISSUE" if menu_index == 0 else "RETURN"
                # !!! JUMP TO SCAN MODE INSTEAD OF LIST !!!
                current_state = 6
            time.sleep(0.5)

    # --- STATE 6: CAMERA SCAN ---
    elif current_state == 6:
        # Run the blocking scan function
        scanned_code = perform_scan()

        if scanned_code:
            # QR Found!
            if scanned_code in books_db:
                selected_isbn = scanned_code
                # Go to confirmation
                lbl_book_confirm_header.text = f"{current_mode}:\n{books_db[selected_isbn]['title']}"
                confirm_index = 0; update_book_confirm_ui(0)
                display.root_group = book_confirm_group
                current_state = 5
            else:
                # Scanned something, but not in DB
                lbl_greeting.text = "Book Not\nIn Database"; display.root_group = greeting_group; time.sleep(2)
                display.root_group = main_group; current_state = 0
        else:
            # Cancelled (Manual Button pressed) -> Go to Manual List
            lbl_list_header.text = f"{current_mode} (MANUAL)"
            book_index = 0; update_book_list_ui(0)
            display.root_group = selection_group
            current_state = 1

        # Debounce to prevent accidental clicks after scan
        time.sleep(0.5)

    # --- STATE 1: MANUAL SELECTION (Fallback) ---
    elif current_state == 1:
        if not btn_up.value: book_index = (book_index - 1) % 5; update_book_list_ui(book_index); time.sleep(0.2)
        if not btn_down.value: book_index = (book_index + 1) % 5; update_book_list_ui(book_index); time.sleep(0.2)
        if not btn_left.value: display.root_group = main_group; current_state = 0; time.sleep(0.5)
        if not btn_ok.value:
            selected_isbn = book_keys[book_index]
            lbl_book_confirm_header.text = f"{current_mode}?"
            confirm_index = 0; update_book_confirm_ui(0)
            display.root_group = book_confirm_group
            current_state = 5; time.sleep(0.5)

    # --- STATE 5: BOOK CONFIRMATION ---
    elif current_state == 5:
        if not btn_up.value: confirm_index = 0; update_book_confirm_ui(0); time.sleep(0.2)
        if not btn_down.value: confirm_index = 1; update_book_confirm_ui(1); time.sleep(0.2)
        if not btn_ok.value:
            if confirm_index == 0:  # YES
                if current_mode == "ISSUE":
                    h, b, f = issue_book_logic(current_user, selected_isbn)
                else:
                    h, b, f = return_book_logic(current_user, selected_isbn)
                current_fine = f
                lbl_confirm_header.text = h; lbl_confirm_header.color = 0xFFFFFF if "SUCCESS" in h or "RETURNED" in h else 0xFF0000
                lbl_confirm_body.text = wrap_text(b, 18)
                lbl_back.text = "Press OK to pay" if (current_mode == "RETURN" and f > 0) else "Press OK to go back"
                display.root_group = confirm_group; current_state = 2
            else:  # NO
                display.root_group = main_group; current_state = 0
            time.sleep(0.5)

    # --- STATE 2: RESULT ---
    elif current_state == 2:
        if not btn_ok.value:
            if current_mode == "RETURN" and current_fine > 0:
                qr_tile = generate_qr(current_fine)
                qr_group.append(qr_tile)
                display.root_group = qr_group; current_state = 7
            else:
                display.root_group = main_group; current_state = 0
            time.sleep(0.5)

    # --- STATE 7: QR PAY DISPLAY ---
    elif current_state == 7:
        if not btn_ok.value:
            qr_group.pop(); display.root_group = main_group; current_state = 0; time.sleep(0.5)

    time.sleep(0.01)
