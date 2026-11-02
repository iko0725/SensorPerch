#!/usr/bin/env bash
# Stream the RealSense colour image to the workstation over UDP (H.264, MPEG-TS).
#   bash camera_stream.sh <workstation_ip>
WORKSTATION_IP="${1:?usage: bash camera_stream.sh <workstation_ip>}"

ffmpeg -stats -loglevel info \
  -f v4l2 -framerate 30 -video_size 640x480 -input_format yuyv422 -i /dev/video4 \
  -vf format=yuv420p \
  -c:v libx264 -preset ultrafast -tune zerolatency \
  -x264-params keyint=15:min-keyint=15:scenecut=0:bframes=0 \
  -b:v 2M -maxrate 2M -bufsize 2M \
  -f mpegts "udp://${WORKSTATION_IP}:5001?pkt_size=1316"
