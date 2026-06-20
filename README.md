# MeshCore TAK Gateway System Documentation

---

### 1. Introduction to Objectives and Architecture

The primary objective of the MeshCore TAK Gateway system is to establish a bridge between an off-grid, decentralized LoRa mesh tracking network and a centralized Cursor on Target (CoT) tactical situational awareness server (Argustak).

The gateway continuously polls or receives local telemetry and contact updates from a mesh companion radio connected via a physical serial interface. This telemetry is dynamically translated into MIL-STD / TAK-compliant CoT XML data packets and streamed over a secure network connection to maintain a real-time common operational picture (COP).

---

### 2. System Component Architecture Diagram

Below is the structural relationship between the field infrastructure, local processing nodes, and the upstream server:

---

### 3. Hardware Requirements

To deploy and operate the gateway ecosystem fully, the following hardware assets are required:

* **Raspberry Pi:** Serves as the central local computing unit running the Linux OS, virtual environments, and the gateway routing pipeline service.
* **SenseCAP Solar Node P1-Pro:** Deployed as the localized companion gateway device physically attached to the Raspberry Pi to handle RF transactions, or configured standalone as high-power node routers.
* **Wio Tracker L1 Pro:** Field terminal transmitting telemetry updates through the LoRa mesh network.
* **SenseCAP Card Tracker T1000-E:** Portable GPS tracker utilized for field deployment within compatible LoRa infrastructure boundaries.


```mermaid
graph TD
    %% Styling Classes
    classDef field fill:#ffebeb,stroke:#ff3333,stroke-width:2px;
    classDef base fill:#f0f5ff,stroke:#1d3557,stroke-width:2px;
    classDef soft fill:#e8fdf5,stroke:#2a9d8f,stroke-width:2px;
    classDef server fill:#fff9e6,stroke:#ffb703,stroke-width:2px;

    subgraph FIELD_LEVEL["FIELD LEVEL (MESH)"]
        Trackers["Multi-Tracker Fleet<br/>• Wio Tracker L1 Pro<br/>• SenseCAP T1000-E"]
        Repeater["Solar Powered Repeater<br/>(SenseCAP Solar Node P1-Pro)"]
    end
    class Trackers,Repeater field;

    subgraph GATEWAY_LAYER["GATEWAY BASE STATION LAYER"]
        Companion["MeshCore Companion Radio Device"]
        subgraph PI_HARDWARE["RASPBERRY PI BASE STATION HARDWARE"]
            subgraph SOFTWARE_STACK["Gateway Software Stack (Python)"]
                MeshCLI["meshcli Wrapper<br/>• floodadv utility<br/>• reset_path (rp)"]
                PollingEngine["Outbound Polling Engine<br/>• req_telemetry<br/>• Telemetry Parser"]
                CoTGen["CoT XML Generator Core"]
            end
            OverlayFS["Local RAM Allocation:<br/>Ephemeral Workspace (OverlayFS)"]
        end
    end
    class Companion,MeshCLI,PollingEngine,CoTGen,OverlayFS base;
    class SOFTWARE_STACK soft;

    subgraph SERVER_LAYER["CLOUD / SERVER LAYER (TAK)"]
        subgraph OPEN_TAK["ARGUSTAK SERVER (OpenTAKServer Deployment)"]
            EudHandler["EudHandlerSSL<br/>(Ingestion Lane)"]
            RabbitMQ["Message Queue<br/>(RabbitMQ Broker)"]
            Postgres["Database Store<br/>(PostgreSQL Core)"]
            WebUI["Presentation UI<br/>(Live TAK Map)"]
        end
    end
    class EudHandler,RabbitMQ,Postgres,WebUI server;

    Trackers <-->|Unicast / Mesh RF| Repeater
    Trackers <-->|Direct Peer-to-Peer RF| Companion
    Repeater <-->|Flood Routing| Companion
    Companion <-->|Serial / USB Interface<br/>/dev/ttyACM0| MeshCLI
    Companion <-->|Serial / USB Interface| PollingEngine
    MeshCLI --> CoTGen
    PollingEngine --> CoTGen
    CoTGen -->|Ethernet RJ-45 @ 192.168.1.238<br/>mTLS Encrypted TCP Stream via Port 8089| EudHandler
    EudHandler --> RabbitMQ
    RabbitMQ --> Postgres

---

### 4. Raspberry Pi Initial Network Configuration

Follow these deployment steps to provision the Raspberry Pi base station unit:

1. **Fixed Ethernet Connection:** Connect a physical RJ-45 Ethernet cable to the Raspberry Pi. Configure the network interface file or NetworkManager to bind to a static, fixed IP address:
* **IP Address:** `192.168.1.238`


2. **Remote Access Credentials:** Once connected, remote terminal management can be accessed using standard network protocols:
* **Username:** `meshcore`
* **Password:** `meshcore`
* *Note:* Access via SSH using `ssh meshcore@192.168.1.238` or open a VNC graphical session to manage configuration elements using the same credentials.


3. **Wi-Fi Infrastructure Setup:** After establishing a baseline connection over Ethernet, use the command line utility or desktop interface to configure the wireless network interface (`wlan0`).

---

### 5. Downloading and Preparing Argustak Server Credentials

Secure communications with `argustak.com` on port `8089` require strict mutual TLS (mTLS) authentication. Anonymous connections on this port will cause immediate backend rejection.

#### Phase A: Exporting the Cryptographic Package

1. Log into your assigned administrator portal via the OpenTAKServer Web UI Dashboard.
2. Navigate to the **Users** or **Manage Certificates** subsection.
3. Locate your user profile and choose to export/download the certificate data bundle. This will download a `.zip` package containing a `.p12` cryptographic file or raw keys.

#### Phase B: Extracting and Cleaning Files via OpenSSL

Modern operating systems utilizing OpenSSL 3.0 require explicit flags to extract cryptographic containers generated with legacy algorithms. Run these extraction commands inside your environment:

```bash
# Extract the client private key using the legacy engine
openssl pkcs12 -in truststore.p12 -nocerts -nodes -out client.key -passin pass:atakatak -legacy

# Extract the client public certificate
openssl pkcs12 -in truststore.p12 -clcerts -nokeys -out client.crt -passin pass:atakatak -legacy

```

Verify that your completed destination files (`truststore.pem`, `client.crt`, and `client.key`) are placed directly within your gateway runtime folder and begin cleanly with their matching `-----BEGIN ...` headers.

---

### 6. Field Tracker User Configuration

To ensure clean field telemetry and uninterrupted communications, tracker nodes must be explicitly configured via the mobile **MeshCore App**:

* **Position Settings:** Access the position layout panel and verify **GPS is enabled**. This guarantees that valid global coordinates are packed into the Low Power Payload (LPP) arrays.
* **Telemetry Permissions:** Adjust permissions to ensure **telemetry is allowed from everyone**. If restricted, the gateway companion node will be blocked from explicitly requesting or parsing location parameters.
* **Contact Settings:** Enable **auto add chat users**. This configuration enables discovery of the companion device across the mesh.
* **Frequency Allocation:** Set the tracker array to the newly designated operational channel frequency defined for your deployment group to ensure clear path propagation and minimize interfering traffic.

---

### 7. Developer/Maintenance Documentation for Gateway Software

The gateway core architecture (`meshcore_advert_ots_gateway_v1.0.py`) operates as a single-threaded execution pipeline looping at a designated interval. Understanding this flow is essential for script maintenance:

* **Execution Order:** Rather than relying on race-prone concurrent threads, the script fires sequence loops in a clean, deterministic order: **Flood Advert Transmission $\rightarrow$ Contact Roster Sync $\rightarrow$ Outbound Telemetry Routing Loop $\rightarrow$ Cooldown Cooldown Cooldown Sleep**.
* **Action 1 (Flood Advertisement):** Uses `subprocess.run` to call the `meshcore-cli` system binary, sending a `-s [SERIAL_PORT] floodadv` parameter string to force the companion radio to broadcast an immediate flood-routed presence advert across the mesh.
* **Action 2 (Contact Roster Sync):** Invokes the `contact_roster_sync_worker()` to read node information from the physical serial port and build local memory lookups. This method handles incoming strings and matches radio hexadecimal identifiers using rigid regex string patterns.
* **Action 3 (Outbound Telemetry Routing Engine):** The script loops through active field nodes and transmits point-to-point (unicast) `req_telemetry` commands.
* *Routing Maintenance Note:* Because point-to-point commands rely on cached RF routing paths, a moving tracker that falls out of range of a direct connection will drop tracking packets. If a node transitions behind a solar-powered repeater, the gateway must drop stale routing entries by preceding the collection sequence with a `reset_path` (alias `rp`) command to force path rediscovery via the repeater network.


* **XML Generation & Timing Validation:** Extracted node parameters are packed into CoT templates. Maintainers must ensure all timestamps are generated using strict absolute Zulu (UTC/GMT) time formats. If the `stale` lifespan attribute is too short, upstream ingestion queues will flag the packets as expired and drop them from the map interface.

```mermaid
sequenceDiagram
    autonumber
    participant Trackers as Trackers (Field Nodes)
    participant Repeater as Solar Repeater (P1-Pro)
    participant Radio as MeshCore Companion (Radio HW)
    participant Pi as Raspberry Pi Gateway (Python Script)
    participant Server as Argustak Server (argustak.com:8089)

    note over Pi: Every 60 Seconds Loop Resumes
    Pi->>Radio: Send floodadv (Flood Advertisement)
    Radio-->>Repeater: Broadcast Flood
    Radio-->>Trackers: Broadcast Flood
    
    Pi->>Radio: Clear stale path (meshcli reset_path)
    Pi->>Radio: Polling Request (req_telemetry ID)
    
    alt Direct path fails
        Radio->>Repeater: Unicast via Repeater
        Repeater->>Trackers: Forward Request
        Trackers->>Repeater: Send GPS Location (LPP)
        Repeater->>Radio: Route Data Back
    else Direct path works
        Radio->>Trackers: Direct Point-to-Point Request
        Trackers->>Radio: Send GPS Location (LPP)
    end

    Radio->>Pi: Stream Raw Byte String over USB
    
    note over Pi: Validation Checks:<br/>1. Filter out non-JSON<br/>2. Decode LPP array<br/>3. Pull strict UTC time<br/>4. Format CoT XML<br/>5. Set 1-Hr Stale Window
    
    Pi->>Server: Establish mTLS (Load client.crt / client.key)
    Server->>Pi: TLS 1.3 Handshake Completed
    Pi->>Server: Stream CoT XML Payload (Ends with '\n', no XML headers)
    
    note over Server: Server Backend Core:<br/>1. Route to RabbitMQ<br/>2. cot_parser DB Write<br/>3. Render Target on Live Map

---

### 8. Python Environment Installation and Prerequisites

To build the required execution workspace on the Raspberry Pi terminal, run the following setup script sequence:

```bash
# Update local repository indexes
sudo apt update && sudo apt install -y python3 python3-pip python3-venv

# Initialize isolated python virtual environment
python3 -m venv ~/meshcore_env

# Activate the virtual environment
source ~/meshcore_env/bin/activate

# Install any essential wheels or dependencies required by the CLI tool core
pip install --upgrade pip

```

---

### 9. System Initialization and Persistence State

* **Automatic Boot Execution:** The core gateway script is configured to initialize instantly on system startup via a systemd background service profile.
* **Resiliency and State Recovery:** The companion radio hardware contains non-volatile storage to permanently house its contact list. If the Raspberry Pi undergoes an unexpected power disruption or reboot cycle, the system will cleanly read existing contact targets immediately upon waking up.

---

### 10. Managing the Gateway Service via Systemd

The runtime lifespan of the gateway automation loop is managed by the system service manager. Use the following commands to control and check the state of the system:

* **Start the Service:**
```bash
sudo systemctl start mesh-gateway.service

```


* **Restart the Service:**
```bash
sudo systemctl restart mesh-gateway.service

```


* **Stop the Service:**
```bash
sudo systemctl stop mesh-gateway.service

```


* **Monitor Service Status & Live Logs:**
```bash
sudo systemctl status mesh-gateway.service

```



---

### 11. Manual Testing and Interactive Execution Procedure

If debugging code updates or testing serial port connectivity manually, you must stop the active background systemd service first to avoid serial lock collisions. Execute the test stack using this precise command sequence:

```bash
# Stop background service to free the serial interface port
sudo systemctl stop mesh-gateway.service

# Activate the environment and execute the program file interactively
source ~/meshcore_env/bin/activate
cd ~/meshcore_env/
python3 meshcore_advert_ots_gateway_v1.0.py

```

---

### 12. Companion Radio Configuration Matrix

The hardware companion device connected directly to the gateway Raspberry Pi must mirror your client tracking criteria. Ensure that inside its local persistent parameters, **auto add chat users** is explicitly enabled within its contact settings layout. This allows the local companion to establish automatic mesh link state mapping with external incoming node traffic without requiring manual intervention.

---

### 13. Hardware Companion Connection Troubleshooting

When hot-plugging the companion radio via the USB/serial interface, or when shifting operations from direct manual command line entries back to automated script execution loops, the serial port abstraction layer may occasionally fail to identify the interface state.

* **Remediation:** Manually reset the companion unit by **pressing the top orange button located on the side of the device**. This forces an internal hardware restart sequence, prompting the OS kernel layer to properly re-enumerate the device path (e.g., `/dev/ttyACM0`).

---

### 14. Field Tracker Diagnostics and Feedback Responses

* **Audible Advert Verification:** When an advertisement or coordination packet is triggered, a **double press** on the field tracker button should cause the unit to emit an audible **beep**. This serves as physical confirmation that the transmitter is active and broadcasting RF frames.
* **Performance Remediation:** Field trackers can become sluggish or unresponsive over long operational durations. If a tracker stops replying to standard gateway poll commands, it should be rebooted. The most reliable method is to open the companion mobile application, navigate to **Settings**, and select the **Reboot Device** command to trigger a clean software cycle.

---

### 15. OverlayFS File System Operation & RAM Log Management

#### OverlayFS Image Overview

To protect the local Raspberry Pi SD card from premature write cycle failure, the system should operate utilizing an OverlayFS file system structure. This configuration locks the base system data as a Read-Only (RO) layer. All active, live modifications, system adjustments, and logging actions are written directly into a dynamic Read-Write (RW) workspace allocated inside system RAM.

#### Toggling OverlayFS via the Terminal GUI

1. Open a terminal session on the Raspberry Pi and launch the internal setup configuration engine:
```bash
sudo raspi-config

```


2. Use the arrow keys to descend to **Performance Options** and select it.
3. Locate the **Overlay File System** configuration row.
4. Select **Enable** to protect your storage layout, or choose **Disable** if you need to perform permanent package updates or script configuration updates.
5. Exit the configuration interface and select **Yes** to reboot the hardware base station to commit the file system layer state change.

#### Crucial RAM and Log Management Warning

Because an enabled OverlayFS shifts all write actions away from physical storage and routes them straight into system memory, verbose script logs or system output can cause quick storage exhaustion. If the gateway script runs with verbose outputs or `DEBUG_MODE = True` over long periods without system rotation, the allocated memory partition will become completely filled.

**Preventative Maintenance:** Ensure `DEBUG_MODE` is set to `False` for standard field operations. Configure log rotation limits inside temporary logging directories, or establish periodic scheduled device reboots to flush the ephemeral RAM storage workspace. This prevents memory starvation crashes and keeps the gateway system stable.# Meshcore-TAK-Gateway
