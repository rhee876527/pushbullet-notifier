#!/usr/bin/env python3
import socket
import ssl
import base64
import hashlib
import struct
import json
import urllib.request
import os
import subprocess
import time
import logging
from pathlib import Path

# Configuration
API_KEY = os.getenv("PUSHBULLET_API_KEY", "")
DEVICE_ID = os.getenv("PUSHBULLET_DEVICE_ID", "")
if not API_KEY or not DEVICE_ID:
    print("Missing API_KEY or DEVICE_ID. Set them as environment variables.")
    exit(1)

HOST = "stream.pushbullet.com"
PORT = 443
WS_PATH = f"/websocket/{API_KEY}"
PUSHES_URL = "https://api.pushbullet.com/v2/pushes"
CACHE_DIR = Path.home() / ".cache"
CACHE_FILE = CACHE_DIR / "pushbullet_messages"
TIMESTAMP_FILE = CACHE_DIR / "pushbullet_last_timestamp"
RECONNECT_DELAY = 5  
PING_INTERVAL = 30    
FETCH_INTERVAL = 300  

# Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
received_timestamps = set()
processed_ids = set()
MAX_PROCESSED_IDS = 1000
CACHE_DIR.mkdir(exist_ok=True)

def load_last_timestamp():
    """Load the last processed timestamp."""
    if TIMESTAMP_FILE.exists():
        return float(TIMESTAMP_FILE.read_text().strip())
    return 0

def save_last_timestamp(timestamp):
    """Save the last processed timestamp."""
    TIMESTAMP_FILE.write_text(str(timestamp))

def append_to_cache(message, timestamp, source=""):
    """Append a message to the cache file with timestamp."""
    human_time = time.ctime(timestamp)
    cache_entry = f"{timestamp} {human_time}: {message}"
    if source:
        cache_entry += f" [{source}]"
    with open(CACHE_FILE, "a") as f:
        f.write(cache_entry + "\n")
        
def create_websocket_connection():
    """Establish a WebSocket connection with Pushbullet."""
    key = base64.b64encode(os.urandom(16)).decode()
    expected_accept = base64.b64encode(
        hashlib.sha1((key.encode() + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11")).digest()
    ).decode()

    context = ssl.create_default_context()
    sock = socket.create_connection((HOST, PORT), timeout=10)
    ssl_sock = context.wrap_socket(sock, server_hostname=HOST)

    handshake = (
        f"GET {WS_PATH} HTTP/1.1\r\n"
        f"Host: {HOST}\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n\r\n"
    )
    ssl_sock.sendall(handshake.encode())

    response = ssl_sock.recv(1024).decode('utf-8', errors='ignore')
    if "101 Switching Protocols" not in response or expected_accept not in response:
        ssl_sock.close()
        return None
    
    return ssl_sock

def send_ping(sock):
    """Send a WebSocket ping frame."""
    try:
        sock.sendall(struct.pack("!BB", 0x89, 0))
        return True
    except socket.error:
        return False

def read_frame(sock):
    """Read WebSocket frame and return payload."""
    try:
        sock.settimeout(30)
        first_byte, second_byte = struct.unpack("!BB", sock.recv(2))
        opcode = first_byte & 0x0F
        masked = second_byte >> 7
        payload_length = second_byte & 0x7F

        if payload_length == 126:
            payload_length = struct.unpack("!H", sock.recv(2))[0]
        elif payload_length == 127:
            payload_length = struct.unpack("!Q", sock.recv(8))[0]

        mask = sock.recv(4) if masked else None
        payload = bytearray(sock.recv(payload_length))

        if masked and mask:
            for i in range(payload_length):
                payload[i] ^= mask[i % 4]

        if opcode != 1:  # Not a text frame
            return None

        message = payload.decode("utf-8", errors="ignore")
        data = json.loads(message)
        created = data.get("created", 0)

        if created and created in received_timestamps:
            return None  # Ignore duplicate messages

        received_timestamps.add(created)
        return message
    except (socket.timeout, ConnectionResetError, BrokenPipeError):
        return None  # Ignore expected connection errors
    except Exception:
        return None  # Ignore other errors silently

def process_message(message_id, content, timestamp, source=""):
    """Process a new message."""
    if message_id in processed_ids:
        return
        
    title = "Pushbullet" if not source else f"Pushbullet [{source}]"
    subprocess.run(["notify-send", title, content])
    append_to_cache(content, timestamp, source)
    processed_ids.add(message_id)
    
    # Limit the size of processed_ids
    if len(processed_ids) > MAX_PROCESSED_IDS:
        processed_ids.remove(next(iter(processed_ids)))

def fetch_new_pushes():
    """Fetch messages newer than the last timestamp."""
    last_timestamp = load_last_timestamp()
    request = urllib.request.Request(PUSHES_URL, headers={"Access-Token": API_KEY})
    
    try:
        with urllib.request.urlopen(request) as response:
            data = json.loads(response.read().decode())
            pushes = data.get("pushes", [])
            
            new_timestamp = last_timestamp
            for push in sorted(pushes, key=lambda x: x.get("created", 0)):
                created = push.get("created", 0)
                if created <= last_timestamp or not push.get("active", True):
                    continue
                    
                target_device = push.get("target_device_iden")
                channel_iden = push.get("channel_iden", "")
                sender_name = push.get("sender_name", "Unknown Sender")
                title = push.get("title", "")
                message = push.get("body") or push.get("url") or push.get("file_url") or "No message"
                
                # Determine source
                if channel_iden:
                    source = f"{sender_name}: \n{title}"
                elif target_device == DEVICE_ID:
                    source = ""
                elif target_device is None:
                    source = "All Devices"
                else:
                    continue  # Not for this device
                    
                process_message(push.get("iden"), message, created, source)
                new_timestamp = max(new_timestamp, created)
            
            save_last_timestamp(new_timestamp)
    except Exception as e:
        logging.error(f"Error fetching new pushes: {str(e)}")


def handle_push_data(push):
    """Process push data from websocket or API."""
    created = push.get("created", 0)
    target_device = push.get("target_device_iden")
    channel_iden = push.get("channel_iden", "")
    sender_name = push.get("sender_name", "Unknown Sender")
    message = push.get("body") or push.get("url") or push.get("file_url") or "No message"
    
    # Determine source
    if channel_iden:
        source = f"Channel: {sender_name}"
    elif target_device == DEVICE_ID:
        source = ""
    elif target_device is None:
        source = "All Devices"
    else:
        return  # Not for this device
        
    process_message(push.get("iden"), message, created, source)

def main_loop():
    backoff_time = RECONNECT_DELAY
    max_backoff = 300  # 5 minutes
    last_fetch_time = time.time()

    while True:
        try:
            ssl_sock = create_websocket_connection()
            if not ssl_sock:
                raise Exception("Failed to establish WebSocket connection")

            logging.info("WebSocket connection established")
            backoff_time = RECONNECT_DELAY  # Reset backoff on successful connection
            last_ping = time.time()

            while True:
                current_time = time.time()
                
                # Send periodic pings
                if current_time - last_ping >= PING_INTERVAL:
                    if not send_ping(ssl_sock):
                        raise Exception("Connection lost")
                    last_ping = current_time

                # Periodic fetch for missed messages
                if current_time - last_fetch_time >= FETCH_INTERVAL:
                    fetch_new_pushes()
                    last_fetch_time = current_time

                # Process incoming messages
                message = read_frame(ssl_sock)
                if message:
                    data = json.loads(message)
                    if data.get("type") == "tickle" and data.get("subtype") == "push":
                        fetch_new_pushes()
                    elif data.get("type") == "push":
                        handle_push_data(data.get("push", {}))
                else:
                    time.sleep(0.1)  # Add a small delay when no message is received

        except KeyboardInterrupt:
            logging.info("Keyboard interrupt received. Exiting.")
            break
        except Exception as e:
            logging.error(f"Connection error: {str(e)}")
            try:
                ssl_sock.close()
            except:
                pass
            if backoff_time >= max_backoff:
                logging.error("Maximum reconnection attempts reached. Exiting service.")
                sys.exit(1)
            time.sleep(backoff_time)
            backoff_time = min(backoff_time * 2, max_backoff)

if __name__ == "__main__":
    # Fetch new messages on startup
    fetch_new_pushes()
    # Start main loop
    main_loop()
