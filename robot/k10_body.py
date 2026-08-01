import network
import usocket as socket
import ujson
import ubinascii
import time
from machine import Pin, PWM
from unihiker_k10 import screen, audio

# --- 1. INITIALIZE DISPLAY ---
screen.init(dir=2)
screen.show_bg(color=0x000000)
screen.draw_text(x=10, y=20, text="Booting Robbie Body...", color=0x00FF00)

# --- 2. WI-FI CONNECTION ---
WIFI_SSID = "YOUR_WIFI_SSID"
WIFI_PASS = "YOUR_WIFI_PASSWORD"

wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.connect(WIFI_SSID, WIFI_PASS)

while not wlan.isconnected():
    time.sleep(0.5)

k10_ip = wlan.ifconfig()[0]
screen.clear()
screen.draw_text(x=10, y=10, text="Robbie Body Ready!", color=0x00FF00)
screen.draw_text(x=10, y=40, text=f"IP: {k10_ip}", color=0xFFFFFF)
print(f"Server live at http://{k10_ip}:8080/robot")

# --- 3. MOTOR:BIT PIN CONFIGURATION ---
# Elecfreaks Motor:bit pin mappings (M1 / M2)
m1_dir = Pin(8, Pin.OUT)     # M1 Direction Pin
m1_pwm = PWM(Pin(1), freq=1000) # M1 Speed Pin
m2_dir = Pin(12, Pin.OUT)    # M2 Direction Pin
m2_pwm = PWM(Pin(2), freq=1000) # M2 Speed Pin

def drive_motors(direction, speed_level, duration_sec):
    if duration_sec <= 0 or speed_level <= 0:
        return
        
    # Scale speed (1-9) to PWM duty cycle (0-1023)
    duty = int((speed_level / 9.0) * 1023)
    
    if direction == "forward":
        m1_dir.value(0)
        m2_dir.value(0)
        m1_pwm.duty(duty)
        m2_pwm.duty(duty)
    elif direction == "backward":
        m1_dir.value(1)
        m2_dir.value(1)
        m1_pwm.duty(duty)
        m2_pwm.duty(duty)
    elif direction == "spin_left":
        m1_dir.value(1)
        m2_dir.value(0)
        m1_pwm.duty(duty)
        m2_pwm.duty(duty)
    elif direction == "spin_right":
        m1_dir.value(0)
        m2_dir.value(1)
        m1_pwm.duty(duty)
        m2_pwm.duty(duty)
        
    time.sleep(duration_sec)
    
    # Stop motors safely
    m1_pwm.duty(0)
    m2_pwm.duty(0)

def set_expression(expr_name):
    screen.clear()
    screen.draw_text(x=10, y=10, text=f"IP: {k10_ip}", color=0x888888)
    # Display face text / status
    screen.draw_text(x=50, y=120, text=f"[{expr_name.upper()}]", color=0x00FFFF)

def play_base64_audio(b64_string):
    if not b64_string:
        return
    try:
        # Decode base64 WAV payload and save to temporary file
        wav_bytes = ubinascii.a2b_base64(b64_string)
        with open("/temp_speech.wav", "wb") as f:
            f.write(wav_bytes)
        
        # Play local WAV file over K10 speaker
        audio.play_wav("/temp_speech.wav")
    except Exception as e:
        print("Audio playback error:", e)

# --- 4. HTTP SERVER LOOP ---
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(('', 8080))
server.listen(2)

while True:
    try:
        conn, addr = server.accept()
        request = conn.recv(4096).decode('utf-8', 'ignore')
        
        # Locate JSON payload in HTTP POST request
        json_start = request.find('{')
        if json_start != -1:
            raw_json = request[json_start:]
            data = ujson.loads(raw_json)
            
            # Send HTTP 200 response immediately
            conn.send('HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{"ok":true}')
            conn.close()
            
            # Execute robot actions
            expression = data.get("expression", "calm")
            direction = data.get("direction", "")
            duration = data.get("duration_seconds", 0)
            speed = data.get("speed", 5)
            audio_b64 = data.get("audio", None)
            
            set_expression(expression)
            
            # Play speech and drive motors concurrently/sequentially
            if audio_b64:
                play_base64_audio(audio_b64)
            if direction and duration > 0:
                drive_motors(direction, speed, duration)
        else:
            conn.send('HTTP/1.1 400 Bad Request\r\n\r\n')
            conn.close()
            
    except Exception as e:
        print("HTTP Error:", e)