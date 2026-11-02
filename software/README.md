# SensorPerch software

[[`Paper`](https://arxiv.org/abs/2607.10682)] [[`Project Page`](https://emprise.cs.cornell.edu/sensorperch/)] [[`Main README`](../README.md)]

The code is split by the computer it runs on:

| Folder | Runs on | What it does |
|---|---|---|
| [`raspberry-pi/`](raspberry-pi) | The Raspberry Pi inside the SensorPerch module | Streams the camera, drives the gimbal, reads the e-stop button |
| [`workstation/`](workstation) | Your Linux workstation, with ROS | Receives the camera stream, sends gimbal commands |
| [`esp32/`](esp32) | An ESP32 board (optional) | Drives the gimbal from physical buttons, without the Pi |

Each job has a sender on one side and a receiver on the other:

| Job | On the Raspberry Pi | On the workstation |
|---|---|---|
| Camera | `camera_stream.sh` sends the RealSense image over UDP port 5001 | `camera_ros_publisher.py` receives it and publishes a ROS image topic |
| Gimbal | `gimbal_server.py` receives commands on UDP port 6000 and moves the servos | `gimbal_client.py` sends commands from the command line; `gimbal_ros_bridge.py` sends them from a ROS topic |
| Gimbal, by hand | `gimbal_keyboard.py` moves the servos from the Pi's keyboard | |
| E-stop | `estop_button.py` reads the assistive button | |

The gimbal has two servos, called blue and green after their colours in the CAD; commands and topics use these names.

## :clipboard: Requirements

- Raspberry Pi (any model with USB 3.0 recommended; SensorPerch uses a Raspberry Pi 4B)
- Intel RealSense camera (D435, D455, etc.; SensorPerch uses a D435i)
- Linux workstation with network connectivity
- Both devices on the same network

**Raspberry Pi**
- FFmpeg with H.264 support
- V4L2 drivers
- RealSense camera drivers
- [pigpio](https://github.com/joan2937/pigpio) for the gimbal servos (see [Gimbal](#joystick-gimbal))

**Linux workstation**
- ROS, GStreamer and FFplay
- Network access to the Pi
- Firewall open for the stream's UDP port (5001)

## :rocket: Quick start

### 1. Network setup

Make sure both devices are on the same network and can reach each other:

```bash
# On the Pi: test the connection to the workstation
ping <workstation_ip>
```

### 2. Firewall (workstation)

```bash
# Check the firewall status
sudo ufw status

# Allow UDP port 5001
sudo ufw allow 5001/udp
sudo ufw reload
```

<details>
<summary><b>Test basic UDP connectivity</b></summary>

On the workstation:

```bash
nc -u -l 5001
```

On the Pi:

```bash
echo "hello" | nc -u <workstation_ip> 5001
```

</details>

## :camera: Camera streaming

**1. On the Pi**, start the camera stream:

```bash
bash raspberry-pi/camera_stream.sh <workstation_ip>
```

**2. On the workstation**, receive it as a ROS image topic:

```bash
conda deactivate   # if a conda environment is active
python3 workstation/camera_ros_publisher.py
```

> **Important:** run this in the **base system Python**, not in a conda environment. Conda's OpenCV is usually built without GStreamer, which is needed to receive the UDP stream.

The topic is `/camera3/color/image_raw` by default; set `_topic:=` to change it, and `_port:=` for another port.

The options below are alternatives; click one to expand it.

<details>
<summary><b>Just view the stream in a window (GStreamer)</b></summary>

```bash
gst-launch-1.0 -v udpsrc port=5001 buffer-size=5242880 \
  caps="video/mpegts, systemstream=(boolean)true, packetsize=(int)188" ! \
  tsparse ! decodebin ! videoconvert ! autovideosink sync=false
```

</details>

<details>
<summary><b>Run the FFmpeg stream by hand and view it with FFplay</b></summary>

`camera_stream.sh` runs this command; to run it by hand on the Pi:

```bash
ffmpeg -stats -loglevel info \
  -f v4l2 -framerate 30 -video_size 640x480 -input_format yuyv422 -i /dev/video4 \
  -vf format=yuv420p \
  -c:v libx264 -preset ultrafast -tune zerolatency \
  -x264-params keyint=15:min-keyint=15:scenecut=0:bframes=0 \
  -b:v 2M -maxrate 2M -bufsize 2M \
  -f mpegts "udp://<workstation_ip>:5001?pkt_size=1316"
```

View it on the workstation:

```bash
ffplay -fflags nobuffer -flags low_delay -fflags +genpts "udp://@:5001"
```

</details>

<details>
<summary><b>Stream with GStreamer on both sides</b></summary>

Pi (sender):

```bash
gst-launch-1.0 v4l2src device=/dev/video4 ! \
  video/x-raw,format=YUY2,width=640,height=480,framerate=30/1 ! \
  videoconvert ! x264enc tune=zerolatency ! \
  mpegtsmux ! udpsink host=<workstation_ip> port=5001
```

Workstation (receiver):

```bash
gst-launch-1.0 udpsrc port=5001 ! \
  tsdemux ! h264parse ! avdec_h264 ! \
  videoconvert ! autovideosink
```

</details>

<details>
<summary><b>Use the stream as a local camera device</b></summary>

A virtual camera device on the workstation lets you treat the stream as a normal camera plugged into the workstation, so you can run sensor launch files and other programs that expect a local camera.

```bash
# Requirements
sudo apt install -y v4l2loopback-dkms v4l-utils

# Create the virtual camera device
sudo modprobe v4l2loopback devices=1 video_nr=20 card_label="netcam" exclusive_caps=1

# Send the UDP stream to it
ffmpeg -i "udp://@:5001" -f v4l2 -pix_fmt yuv420p /dev/video20

# Use it as a normal camera
ffplay /dev/video20
```

`workstation/launch/realsense.launch` starts the RealSense ROS driver (`realsense2_camera`) for a camera on the workstation.

</details>

<details>
<summary><b>Stream settings</b></summary>

| Video | |
|---|---|
| Resolution | 640 × 480 (adjustable) |
| Frame rate | 30 fps |
| Bitrate | 2 Mbps |
| Codec | H.264, `zerolatency` preset |

| Network | |
|---|---|
| Protocol | UDP |
| Port | 5001 (configurable) |
| Packet size | 1316 bytes |

</details>

## :joystick: Gimbal

**1. On the Pi**, install pigpio and start its daemon (run `sudo pigpiod` again after every reboot):

```bash
sudo apt update
sudo apt install python3-pigpio pigpio-tools
sudo pigpiod
pigs t   # prints a timestamp if the daemon is running
```

**2. On the Pi**, start the gimbal server:

```bash
python3 raspberry-pi/gimbal_server.py --mode udp
```

**3. On the workstation**, start the ROS bridge and send angles on its topic:

```bash
python3 workstation/gimbal_ros_bridge.py _pi_ip:=<pi_ip>

# In a second terminal: blue = 40°, green = 70°
rostopic pub /servo/set std_msgs/Float32MultiArray "data: [40, 70]" -1

# Current angles (always published)
rostopic echo /servo/status
```

| ROS topic | |
|---|---|
| Name | `/servo/set` |
| Message type | `std_msgs/Float32MultiArray` |
| Data | `[blue_servo_angle, green_servo_angle]` |
| Angle range | 0–180 degrees |

All the ways to control the gimbal:

| Mode | On the Raspberry Pi | On the workstation |
|---|---|---|
| ROS | `python3 raspberry-pi/gimbal_server.py --mode udp` | `python3 workstation/gimbal_ros_bridge.py` + `rostopic pub` |
| Command line | `python3 raspberry-pi/gimbal_server.py --mode udp` | `python3 workstation/gimbal_client.py --ip <pi_ip> <command>` |
| Keyboard | `python3 raspberry-pi/gimbal_server.py --mode curses` | |

The options below are alternatives; click one to expand it.

<details>
<summary><b>Control from the workstation's command line, without ROS</b></summary>

With the server running in `--mode udp` on the Pi:

```bash
# Move the blue servo by +5 degrees
python3 workstation/gimbal_client.py --ip <pi_ip> step --blue 5

# Check the current servo status
python3 workstation/gimbal_client.py --ip <pi_ip> status

# Move the servos to the home position
python3 workstation/gimbal_client.py --ip <pi_ip> home
```

Other commands: `set`, `smooth` and `sync` (each with `--blue` and `--green` angles), `game --state start|stop|toggle` for the demo sweep, and `set-step-delay --value <seconds>`.

</details>

<details>
<summary><b>Control from the Pi's keyboard</b></summary>

Through the gimbal server:

```bash
python3 raspberry-pi/gimbal_server.py --mode curses
```

Use the keyboard to move the servos interactively; press `q` to quit.

Or with the standalone keyboard controller:

```bash
python3 raspberry-pi/gimbal_keyboard.py
```

| Key | Action |
|---|---|
| `a` / `d` | Blue servo decrease / increase |
| `w` / `s` | Green servo increase / decrease |
| `g` | Start or stop the demo sweep |
| `q` | Quit |

</details>

<details>
<summary><b>Build pigpio from source</b></summary>

```bash
cd ~
sudo apt install git build-essential
git clone https://github.com/joan2937/pigpio.git
cd pigpio
make
sudo make install
```

</details>

<details>
<summary><b>Test the servos directly</b></summary>

```bash
sudo pigpiod
pigs s 12 1500   # pulse width 1500 µs on GPIO 12
pigs s 13 1500   # pulse width 1500 µs on GPIO 13
```

These set both servos to their neutral position (1500 µs pulse width).

</details>

<details>
<summary><b>Use an ESP32 with buttons instead of the Pi</b></summary>

[`esp32/gimbal_buttons/gimbal_buttons.ino`](esp32/gimbal_buttons/gimbal_buttons.ino) drives the two servos from an ESP32 with physical buttons: servos on GPIO 32 (blue) and 33 (green), buttons on GPIO 18 / 19 (blue + / −) and 25 / 26 (green + / −), and the demo sweep started and stopped on GPIO 12 and 14.

</details>

## :stop_sign: E-stop button

The assistive button is a physical button that connects through the audio jack and is read as an audio input device. It can serve as a soft e-stop or for other controls.

To check that presses are detected, run on the Pi:

```bash
# List the audio input devices
python3 raspberry-pi/estop_button.py

# Watch device 10, with monitoring on and a custom threshold
python3 raspberry-pi/estop_button.py --id 10 --monitor --threshold 200
```

| Option | Meaning |
|---|---|
| `--id <number>` | Audio input device index (required); run without it to list the devices |
| `--monitor` | Print the signal values every 0.5 seconds |
| `--threshold <number>` | Detection threshold (default 200); lower is more sensitive |
| `--debug` | Print detailed debugging output |

The script prints "E-stop pressed!" on each press. Press Ctrl+C to stop.

## :mag: Troubleshooting

Check that the RealSense is detected:

```bash
lsusb | grep Intel
v4l2-ctl --list-devices
```

Check the video devices (the stream reads `/dev/video4`):

```bash
ls -la /dev/video*
v4l2-ctl -d /dev/video4 --all
```

Watch the UDP traffic:

```bash
sudo tcpdump -ni <interface> udp port 5001 -c 10
```

If the servos do not move, start the daemon with `sudo pigpiod` and check it with `pigs t`.

## :zap: Performance

- Connect the RealSense over USB 3.0.
- Keep the network connection stable; wired Ethernet is more stable.
- Adjust the bitrate to the network's capacity.

## :lock: Security

The camera stream and the gimbal commands are unencrypted UDP. Use them on trusted networks only.
