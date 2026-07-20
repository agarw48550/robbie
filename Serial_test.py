import serial
import time

# Replace with your actual port from the terminal command
SERIAL_PORT = '/dev/cu.usbmodem102' 
BAUD_RATE = 115200

def test_serial():
    print(f"Connecting to {SERIAL_PORT}...")
    try:
        # Open serial connection
        with serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1) as ser:
            time.sleep(2) # Give it a moment to initialize
            print("Connection successful! Sending test command...")
            
            # Send a simple command (we'll assume the micro:bit expects newline-terminated strings)
            ser.write(b"1491\n")
            
            # Wait for a potential acknowledgement from the micro:bit
            time.sleep(0.5)
            while ser.in_waiting > 0:
                response = ser.readline().decode('utf-8').strip()
                print(f"Micro:bit replied: {response}")
                
    except serial.SerialException as e:
        print(f"Serial Error: {e}")

if __name__ == "__main__":
    test_serial()