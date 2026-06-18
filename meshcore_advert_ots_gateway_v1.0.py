#!/usr/bin/env python3
import threading
import time
import sys
import ssl
import socket
import json
import subprocess
import re

# --- SYSTEM CONFIGURATION MATRIX ---
DEBUG_MODE = False         # True: prints raw meshcli payloads and link telemetry
USE_FTS = True           # True: streams to FreeTAKServer | False: standalone offline testing
SERIAL_PORT = "/dev/ttyACM0"

TAK_SERVER_IP = "argustak.com"
TAK_SERVER_PORT = 8089  # SSL TCP CoT Stream Port
CA_FILE = "truststore.pem"
CERT_FILE = "client.crt"
KEY_FILE = "client.key"

FLEET_POLL_INTERVAL = 60  # Seconds between automated explicit telemetry polls
GROUP_NAME = "Cyan" # Device TAK name
ROLE = "Team Member" # Device TAK role

# Global lock to protect serial port access across threads
serial_lock = threading.Lock()

class FleetManager:
    def __init__(self):
        # Master tracking registry for active polling targets
        self.registry = {} 
        # Local lookup cache mapping key_prefix -> callsign_id (populated from contacts list)
        self.contacts_cache = {}
        self.lock = threading.Lock()

    def update_contacts_cache_and_populate_fleet(self, raw_contacts_output):
        if not raw_contacts_output:
            print("[-] Warning: Received empty contacts output from device serial port.")
            return

        with self.lock:
            new_cache = {}
            for line in raw_contacts_output.splitlines():
                line_str = line.strip()
                if "info:" in line_str.lower() or "contacts in device" in line_str.lower() or not line_str:
                    continue
                
                # Strip ANSI escape sequences and terminal style modifiers
                clean_line = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', line_str)
                
                # Match exactly a 12-character hex sequence isolated by boundaries
                hex_match = re.search(r'\b([0-9a-fA-F]{12})\b', clean_line)
                if hex_match:
                    hex_prefix = hex_match.group(1).lower()
                    
                    # Split the string to isolate the callsign on the left side
                    parts = clean_line.split()
                    type_index = -1
                    for i, part in enumerate(parts):
                        if part in ["CLI", "REP", "ROOM", "SENS"]:
                            type_index = i
                            break
                    
                    if type_index != -1:
                        # Reconstruct everything before the type identifier as the true ID
                        callsign_id = " ".join(parts[:type_index]).strip()
                        new_cache[hex_prefix] = callsign_id

            self.contacts_cache = new_cache
            
            # Populate registry from persistent contact storage
            for prefix_norm, callsign_id in self.contacts_cache.items():
                if prefix_norm not in self.registry:
                    assigned_index = len(self.registry) + 1
                    fleet_id = f"TRKR-{str(assigned_index).zfill(2)}"
                    
                    self.registry[prefix_norm] = {
                        "fleet_id": fleet_id,
                        "callsign": callsign_id,
                        "first_seen": time.strftime('%H:%M:%S'),
                        "last_seen": time.strftime('%H:%M:%S'),
                        "packet_count": 0
                    }

            print(f"\n==================================================")
            print(f" [DEBUG] PERSISTENT CONTACTS TRANSLATION TABLE RESTORED")
            print(f"==================================================")
            if self.contacts_cache:
                print(f"{'Key Prefix':<18} ----> {'Callsign ID'}")
                print(f"--------------------------------------------------")
                for prefix, callsign in sorted(self.contacts_cache.items()):
                    print(f"{prefix:<18} ----> {callsign}")
            else:
                print(" Matrix is currently EMPTY (No valid contacts parsed).")
            print(f"==================================================\n")

    def register_onboarded_node(self, key_prefix):
        with self.lock:
            # Normalize prefix to check against our 12-char registry keys
            prefix_norm = key_prefix.strip().lower()[:12]
            if prefix_norm in self.contacts_cache:
                callsign_id = self.contacts_cache[prefix_norm]
                if prefix_norm not in self.registry:
                    assigned_index = len(self.registry) + 1
                    fleet_id = f"TRKR-{str(assigned_index).zfill(2)}"
                    self.registry[prefix_norm] = {
                        "fleet_id": fleet_id,
                        "callsign": callsign_id,
                        "first_seen": time.strftime('%H:%M:%S'),
                        "last_seen": time.strftime('%H:%M:%S'),
                        "packet_count": 1
                    }
                    print(f"\n[NEW ASSET ONBOARDED] Callsign: {callsign_id} (Prefix: {prefix_norm}) -> Assigned: {fleet_id}")
                else:
                    self.registry[prefix_norm]["last_seen"] = time.strftime('%H:%M:%S')
                    self.registry[prefix_norm]["packet_count"] += 1
                return True
            return False

    def print_fleet_status(self):
        with self.lock:
            print(f"--- FLEET ROLLOUT STATUS LAYER ({time.strftime('%H:%M:%S')}) ---")
            print(f"{'Fleet ID':<10} | {'Callsign ID':<20} | {'Key Prefix':<18} | {'Last Seen':<10} | {'Packets':<8}")
            print("-" * 75)
            for prefix, meta in sorted(self.registry.items(), key=lambda x: x[1]['fleet_id']):
                print(f"{meta['fleet_id']:<10} | {meta['callsign']:<20} | {prefix:<18} | {meta['last_seen']:<10} | {meta['packet_count']:<8}")
            print(f"Total Active Grid Nodes: {len(self.registry)}\n")


fleet = FleetManager()

# --- CORE SERIAL SUBPROCESS CALLS WITH LOCKING ---
def fetch_device_contacts():
    with serial_lock:
        try:
            result = subprocess.run(
                ["/home/meshcore/meshcore_env/bin/meshcore-cli", "-s", SERIAL_PORT, "contacts"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=12
            )
            return result.stdout
        except Exception as e:
            print(f"[-] Execution failure accessing serial port interface: {e}")
            return ""

# --- NETWORK LAYER: FTS LINK MANAGEMENT ---
def format_cot(fleet_id, lat, lon, callsign, voltage):
    now = time.time()
    time_str = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(now))
    stale_str = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(now + 120))
 
# Quick conversion example if mapping 3.4V-4.2V to a rough 0-100 percentage layout:
    if voltage:
        # Clamping calculation between 0 and 100
        battery_pct = int(max(0, min(100, ((voltage - 3.4) / (4.2 - 3.4)) * 100)))
    else:
        battery_pct = 0
   
    return (
        f'<event version="2.0" uid="{fleet_id}" type="a-f-G-E-S" how="h-g-i-g-o" '
        f'time="{time_str}" start="{time_str}" stale="{stale_str}">'
        f'<point lat="{lat}" lon="{lon}" hae="0.0" ce="10.0" le="10.0"/>'
        f'<detail><contact callsign="{callsign} ({battery_pct}%)"/><status role="{ROLE}"/>'
        f'<group name="{GROUP_NAME}" role="{ROLE}"/></detail></event>\n'
    )

def send_cot_to_fts(xml_payload):
    print(f"[*] Connecting to OpenTAKServer (SSL) at {TAK_SERVER_IP}:{TAK_SERVER_PORT}...")
    try:
        # 1. Initialize an SSL Context designed for a client connection
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.verify_mode = ssl.CERT_REQUIRED

        # 2. Load the Trust Store/CA cert so your script trusts the server
        context.load_verify_locations(cafile=CA_FILE)

        # 3. Load your client identity. 
        # This passes the cert and unencrypted private key directly to the TLS handshake
        context.load_cert_chain(
            certfile=CERT_FILE, 
            keyfile=KEY_FILE
        )

        # 4. Connect to the server
        with socket.create_connection((TAK_SERVER_IP, TAK_SERVER_PORT)) as sock:
            with context.wrap_socket(sock, server_hostname=TAK_SERVER_IP) as ssock:
                print(f"Successfully authenticated via mTLS using Certificate. TLS Version: {ssock.version()}")

                if DEBUG_MODE:
                    print(f"[DEBUG] Sending Payload String:\n{xml_payload}")
            
                # Send the data with the mandatory newline frame delimiter
                ssock.sendall(xml_payload.encode('utf-8') + b'\n')
                time.sleep(1)
                ssock.close()
                print("[+] Secure packet delivered successfully.")

    except Exception as e:
       print(f"[-] Secure network connection error: {e}")

# --- THREAD 1: OUTBOUND TELEMETRY POLLING ENGINE ---
def outbound_polling_engine():
    with fleet.lock:
        # Pull the key prefix identifier and metadata callsign from the registry
        poll_targets = [(prefix, meta["callsign"]) for prefix, meta in fleet.registry.items()]
            
    if poll_targets:
        print(f"[{time.strftime('%H:%M:%S')}] Active Polling Cycle Started: Querying {len(poll_targets)} mesh targets...")
        for prefix, callsign in poll_targets:
            try:
                if DEBUG_MODE:
                    print(f"[DEBUG] Polling target callsign [{callsign}] via meshcore-cli...")
                    
                output = None  # Safe initialization before serial block execution
                
                with serial_lock:
                    try:
                        # Step 1: Tell the radio to reset the path and fall back to flood routing
                        subprocess.run(
                            ["/home/meshcore/meshcore_env/bin/meshcore-cli", "-s", SERIAL_PORT, "reset_path", callsign],
                            stdout=subprocess.PIPE, 
                            stderr=subprocess.PIPE, 
                            text=True, 
                            timeout=10,
                            check=True
                        )
        
                        # Step 2: Request the telemetry payload immediately after path reset
                        result = subprocess.run(
                            ["/home/meshcore/meshcore_env/bin/meshcore-cli", "-j", "-s", SERIAL_PORT, "req_telemetry", callsign],
                            stdout=subprocess.PIPE, 
                            stderr=subprocess.PIPE, 
                            text=True, 
                            timeout=25
                        )
        
                        # Capture output inside the protected block where result assignment is guaranteed
                        output = result.stdout.strip()
                        if DEBUG_MODE and result.stderr:
                            print(f"[DEBUG CLI Stderr]: {result.stderr.strip()}")
        
                    except subprocess.TimeoutExpired as e:
                        print(f"[-] [TIMEOUT] Radio communication timed out: {e}")
                    except subprocess.CalledProcessError as e:
                        print(f"[-] [ERROR] Reset path command failed: {e}")                    
                
                # Forward to the parsing pipeline if a telemetry response was successfully captured
                if output:
                    parse_and_route_packet(output, prefix)
                    
            except Exception as e:
                if DEBUG_MODE:
                    print(f"[DEBUG] Polling timeout/error for entry {callsign}: {e}")
      
    fleet.print_fleet_status()

# --- THREAD 2: INBOUND INBOX MESSAGE COMMAND TRIGGER ---
def contact_roster_sync_worker():
    print(f"[{time.strftime('%H:%M:%S')}] [BOOT] Active Contact Roster Sync Worker Engaged.")
    
    try:
        if DEBUG_MODE:
            print(f"[{time.strftime('%H:%M:%S')}] Polling hardware contact database...")
            
        # Fetch current contacts via the existing CLI utility function
        current_raw_contacts = fetch_device_contacts()
            
        if current_raw_contacts:
            # Update the cache and automatically map any brand new entries
            fleet.update_contacts_cache_and_populate_fleet(current_raw_contacts)
                
    except Exception as e:
        print(f"[-] Roster sync worker encountered an unexpected exception: {e}")

def evaluate_inbox_message(packet):
    text_payload = packet.get('text', '')
    if "tak" in text_payload.lower():
        prefix_key = packet.get('pubkey_prefix', '').strip().lower()
        if not prefix_key:
            return

        print(f"[{time.strftime('%H:%M:%S')}] [ONBOARD REQUEST] Token matching from prefix: {prefix_key}")
        if not fleet.register_onboarded_node(prefix_key):
            raw_table = fetch_device_contacts()
            fleet.update_contacts_cache_and_populate_fleet(raw_table)


def parse_and_route_packet(raw_json_str, fallback_prefix):
    try:
        packet = json.loads(raw_json_str)
        # Normalize target routing keys strictly down to the 12-char format used by the cache registry
        pubkey_pre = packet.get('pubkey_pre', fallback_prefix).strip().lower()[:12]
        
        with fleet.lock:
            if pubkey_pre not in fleet.registry:
                if DEBUG_MODE:
                    print(f"[DEBUG] Packet ignored. Prefix key [{pubkey_pre}] is not mapped in your active fleet registry.")
                return
            meta = fleet.registry[pubkey_pre]
            fleet_id = meta["fleet_id"]
            callsign = meta["callsign"]

            voltage = None
            lat, lon, alt = None, None, None

            for element in packet.get('lpp', []):
                if element.get("type") == "voltage":
                    voltage = element.get('value')
                elif element.get('type') == 'gps':
                    lat = element.get('value', {}).get('latitude')
                    lon = element.get('value', {}).get('longitude')
                    alt = element.get('value', {}).get('altitude')
                    break  
                
        if lat is not None and lon is not None:
            fleet.register_onboarded_node(pubkey_pre)
            print(f"[{time.strftime('%H:%M:%S')}] TRACKING SUCCESS: {fleet_id} ({callsign}) -> Lat: {lat}, Lon: {lon}, Bat:{voltage}")
            
            if USE_FTS:
                xml_string = format_cot(fleet_id, lat, lon, callsign, voltage)
                send_cot_to_fts(xml_string)
                    
    except Exception as e:
        if DEBUG_MODE:
            print(f"[-] Engine skipped payload string parsing: {e}")

# --- MAIN EXECUTION MATRIX ---
if __name__ == "__main__":
    print("==================================================================")
    print(" Meshcore Cascading Persistent Telemetry Gateway Active")
    print(f" Bus Link: {SERIAL_PORT} | FTS Pipeline Forwarding: {USE_FTS}")
    print("==================================================================")

    print(f"[{time.strftime('%H:%M:%S')}] [BOOT] Initializing local contact roster sync...")
    
    initial_contacts = fetch_device_contacts()
    fleet.update_contacts_cache_and_populate_fleet(initial_contacts)
    
    fleet.print_fleet_status()

    # Persistent, sequential execution loop with a 60-second repetition interval
    try:
        while True:
            print(f"\n[{time.strftime('%H:%M:%S')}] [CYCLE START] Beginning scheduled gateway routine...")

            # Step 1: Trigger a flood routed advertisement via meshcore-cli
            print(f"[{time.strftime('%H:%M:%S')}] [ACTION 1] Ordering companion device to send flood advertisement...")
            try:
                # Utilizing the global SERIAL_PORT and meshcli's native floodadv operation
                subprocess.run(["/home/meshcore/meshcore_env/bin/meshcore-cli", "-s", SERIAL_PORT, "floodadv"], check=True)
                print(f"[{time.strftime('%H:%M:%S')}] [SUCCESS] Flood advertisement transmitted successfully.")
            except subprocess.CalledProcessError as e:
                print(f"[-] [ERROR] meshcore-cli failed to broadcast advertisement: {e}")
            except Exception as e:
                print(f"[-] [ERROR] Failed to execute advertisement command: {e}")

            # Step 2: Synchronize the contact roster
            print(f"[{time.strftime('%H:%M:%S')}] [ACTION 2] Executing contact roster synchronization...")
            try:
                contact_roster_sync_worker()
            except Exception as e:
                print(f"[-] [ERROR] Exception caught in contact roster worker: {e}")

            # Step 3: Run the outbound polling pipeline
            print(f"[{time.strftime('%H:%M:%S')}] [ACTION 3] Launching outbound telemetry routing loop...")
            try:
                outbound_polling_engine()
            except Exception as e:
                print(f"[-] [ERROR] Exception caught in outbound polling engine: {e}")

            # Step 4: Cooldown period before repeating the sequence
            print(f"[{time.strftime('%H:%M:%S')}] [CYCLE COMPLETE] Sleeping for 60 seconds...")
            time.sleep(FLEET_POLL_INTERVAL)

    except KeyboardInterrupt:
        print(f"\n[{time.strftime('%H:%M:%S')}] [SHUTDOWN] Gateway loop terminated cleanly by user.")
