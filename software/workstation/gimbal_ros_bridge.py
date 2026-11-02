#!/usr/bin/env python3
import rospy, socket, json
from std_msgs.msg import Float32MultiArray
from std_msgs.msg import String

class ServoBridge:
    def __init__(self):
        self.pi_ip   = rospy.get_param("~pi_ip", "192.168.2.189")
        self.port    = int(rospy.get_param("~port", 6000))
        self.timeout = float(rospy.get_param("~timeout", 1.0))
        self.status_rate = float(rospy.get_param("~status_rate_hz", 2.0))

        self.pub_status = rospy.Publisher("/servo/status", String, queue_size=10)

        rospy.Subscriber("/servo/set",    Float32MultiArray, self.cb_set)
        # rospy.Subscriber("/servo/smooth", Float32MultiArray, self.cb_smooth)
        # rospy.Subscriber("/servo/game",   String,  self.cb_game)

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(self.timeout)

        rospy.loginfo("ServoBridge -> Pi %s:%d", self.pi_ip, self.port)
        self.timer = rospy.Timer(rospy.Duration(1.0/self.status_rate), self.tick_status)

    def send_cmd(self, payload):
        try:
            self.sock.sendto(json.dumps(payload).encode("utf-8"), (self.pi_ip, self.port))
            data, _ = self.sock.recvfrom(4096)
            return json.loads(data.decode("utf-8"))
        except socket.timeout:
            return {"ok": False, "error": "timeout_no_reply"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def cb_set(self, msg):
        if len(msg.data) != 2:
            rospy.logwarn("Expected 2 values: [blue, green]")
            return
        p = {"cmd": "set", "blue": int(msg.data[0]), "green": int(msg.data[1])}
        resp = self.send_cmd(p)
        self.pub_status.publish(String(json.dumps(resp)))

    def cb_smooth(self, msg):
        if len(msg.data) != 2:
            rospy.logwarn("Expected 2 values: [blue, green]")
            return
        p = {"cmd": "smooth", "blue": int(msg.data[0]), "green": int(msg.data[1])}
        resp = self.send_cmd(p)
        self.pub_status.publish(String(json.dumps(resp)))
        
    def cb_game(self, msg):
        resp = self.send_cmd({"cmd":"game", "state": msg.data})
        self.pub_status.publish(String(json.dumps(resp)))

    def tick_status(self, _evt):
        resp = self.send_cmd({"cmd":"status"})
        self.pub_status.publish(String(json.dumps(resp)))

if __name__ == "__main__":
    rospy.init_node("gimbal_ros_bridge")
    ServoBridge()
    rospy.spin()

