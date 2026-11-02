#!/usr/bin/env python3
"""
GStreamer Image Publisher using GStreamer Python bindings directly.
This works even if OpenCV doesn't have GStreamer support.
"""

import os
import cv2
import rospy
import numpy as np
from cv_bridge import CvBridge
from sensor_msgs.msg import Image

# Try to import GStreamer Python bindings
try:
    import gi
    gi.require_version('Gst', '1.0')
    gi.require_version('GstApp', '1.0')
    from gi.repository import Gst, GstApp, GLib
    GSTREAMER_AVAILABLE = True
except ImportError:
    GSTREAMER_AVAILABLE = False
    print("[ERROR] GStreamer Python bindings not available!")
    print("Install with:")
    print("  sudo apt-get install python3-gi python3-gst-1.0 \\")
    print("                     gir1.2-gstreamer-1.0 \\")
    print("                     gir1.2-gst-plugins-base-1.0")
    exit(1)


class GStreamerCapture:
    """GStreamer-based video capture using Python bindings."""
    
    def __init__(self, pipeline_str, port):
        self.pipeline_str = pipeline_str
        self.port = port
        self.pipeline = None
        self.appsink = None
        self.latest_frame = None
        self.frame_available = False
        
        # Initialize GStreamer
        Gst.init(None)
        
    def on_new_sample(self, appsink):
        """Callback when a new frame is available."""
        sample = appsink.emit('pull-sample')
        if sample:
            caps = sample.get_caps()
            structure = caps.get_structure(0)
            width = structure.get_int('width').value
            height = structure.get_int('height').value
            
            # Get buffer
            buffer = sample.get_buffer()
            success, map_info = buffer.map(Gst.MapFlags.READ)
            
            if success:
                # Create numpy array from buffer
                frame_data = map_info.data
                frame_array = np.frombuffer(frame_data, dtype=np.uint8)
                
                # Reshape to image (assuming BGR format from videoconvert)
                frame = frame_array.reshape((height, width, 3))
                
                # Store frame
                self.latest_frame = frame.copy()
                self.frame_available = True
                
                buffer.unmap(map_info)
                return Gst.FlowReturn.OK
        
        return Gst.FlowReturn.ERROR
    
    def create_pipeline(self):
        """Create and configure GStreamer pipeline."""
        # Build pipeline string
        pipeline_str = (
            f'udpsrc port={self.port} buffer-size=5242880 '
            'caps=video/mpegts,systemstream=(boolean)true,packetsize=(int)188 ! '
            'decodebin ! videoconvert ! '
            'video/x-raw,format=BGR ! '
            'appsink name=sink emit-signals=true max-buffers=1 drop=true sync=false'
        )
        
        print(f"[INFO] Creating GStreamer pipeline:")
        print(f"  {pipeline_str}")
        
        # Create pipeline from string
        self.pipeline = Gst.parse_launch(pipeline_str)
        
        if not self.pipeline:
            raise RuntimeError("Failed to create GStreamer pipeline")
        
        # Get appsink element
        self.appsink = self.pipeline.get_by_name('sink')
        if not self.appsink:
            raise RuntimeError("Failed to get appsink element")
        
        # Connect callback
        self.appsink.connect('new-sample', self.on_new_sample)
        
        return True
    
    def start(self):
        """Start the pipeline."""
        if not self.pipeline:
            self.create_pipeline()
        
        # Set pipeline to playing state
        ret = self.pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("Failed to start GStreamer pipeline")
        
        print("[INFO] GStreamer pipeline started")
        return True
    
    def read(self):
        """Read a frame (non-blocking)."""
        if self.frame_available and self.latest_frame is not None:
            frame = self.latest_frame.copy()
            self.frame_available = False
            return True, frame
        return False, None
    
    def isOpened(self):
        """Check if pipeline is opened and running."""
        if not self.pipeline:
            return False
        state = self.pipeline.get_state(0)[1]
        return state == Gst.State.PLAYING
    
    def release(self):
        """Stop and release the pipeline."""
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None
            self.appsink = None


def main():
    print("="*60)
    print("GStreamer Image Publisher (Direct GStreamer)")
    print("="*60)
    
    if not GSTREAMER_AVAILABLE:
        print("[ERROR] GStreamer Python bindings not available!")
        return
    
    rospy.init_node("camera_ros_publisher")
    print(f"[INFO] ROS node initialized: gst_image_pub")

    port      = rospy.get_param("~port", 5001)
    frame_id  = rospy.get_param("~frame_id", "netcam")
    topic     = rospy.get_param("~topic", "/camera3/color/image_raw")
    
    print(f"[INFO] Configuration:")
    print(f"  UDP Port: {port}")
    print(f"  ROS Topic: {topic}")
    print(f"  Frame ID: {frame_id}")
    print()

    # Create GStreamer capture
    print(f"[INFO] Initializing GStreamer pipeline on UDP port {port}")
    try:
        cap = GStreamerCapture(None, port)
        cap.create_pipeline()
        cap.start()
    except Exception as e:
        print(f"[ERROR] Failed to initialize GStreamer: {e}")
        rospy.logfatal(f"GStreamer initialization failed: {e}")
        return
    
    # Wait a moment for pipeline to start
    rospy.sleep(1.0)
    
    # Test if we can read frames
    print("[INFO] Testing frame capture (waiting up to 5 seconds)...")
    test_ok = False
    test_frame = None
    for attempt in range(50):  # Try for 5 seconds
        test_ok, test_frame = cap.read()
        if test_ok and test_frame is not None:
            break
        rospy.sleep(0.1)
    
    if not test_ok or test_frame is None:
        print("[ERROR] Cannot read frames from GStreamer pipeline")
        print("[ERROR] Check if data is arriving and stream format is correct")
        cap.release()
        return
    
    print(f"[SUCCESS] GStreamer pipeline working! Frame shape: {test_frame.shape}")

    pub = rospy.Publisher(topic, Image, queue_size=1)
    bridge = CvBridge()
    print(f"[INFO] Publishing to topic: {topic} (bgr8)")
    print(f"[INFO] Frame ID: {frame_id}")
    rospy.loginfo(f"Publishing {topic} (bgr8) from UDP:{port}")

    # Wait a moment for publisher to register
    rospy.sleep(0.5)
    
    print()
    print("[INFO] To verify it's working, run in another terminal:")
    print(f"  rostopic hz {topic}")
    print(f"  rostopic echo {topic} -n 1")
    print()

    rate = rospy.Rate(30)  # 30 Hz should be sufficient
    frame_count = 0
    last_log_time = rospy.Time.now()
    
    print("[INFO] Starting to capture and publish frames...")
    print("[INFO] Press Ctrl+C to stop")
    print()
    
    try:
        while not rospy.is_shutdown():
            ok, frame = cap.read()
            if not ok or frame is None:
                rospy.logwarn_throttle(5.0, "No frame from GStreamer pipeline")
                rate.sleep()
                continue
            
            frame_count += 1
            msg = bridge.cv2_to_imgmsg(frame, encoding="bgr8")
            msg.header.stamp = rospy.Time.now()
            msg.header.frame_id = frame_id
            pub.publish(msg)
            
            # Log progress every 5 seconds
            now = rospy.Time.now()
            if (now - last_log_time).to_sec() >= 5.0:
                fps = frame_count / (now - last_log_time).to_sec()
                print(f"[INFO] Published {frame_count} frames (~{fps:.1f} fps)")
                rospy.loginfo(f"Published {frame_count} frames (~{fps:.1f} fps)")
                frame_count = 0
                last_log_time = now
            
            rate.sleep()
    except KeyboardInterrupt:
        print("\n[INFO] Interrupted by user")
    finally:
        print("[INFO] Shutting down...")
        cap.release()

if __name__ == "__main__":
    main()
