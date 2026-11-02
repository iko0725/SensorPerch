import argparse, socket, json


'''
Example:
python3 gimbal_client.py --ip 192.168.2.189 step --blue 5

'''
def send(ip, port, payload):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(1.0)
    s.sendto(json.dumps(payload).encode("utf-8"), (ip, port))
    try:
        data, _ = s.recvfrom(4096)
        print(data.decode())
    except Exception:
        pass

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", required=True, help="Pi IP")
    ap.add_argument("--port", type=int, default=6000)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("status")

    p = sub.add_parser("home")

    p = sub.add_parser("set");    p.add_argument("--blue", type=int);  p.add_argument("--green", type=int)

    p = sub.add_parser("smooth"); p.add_argument("--blue", type=int);  p.add_argument("--green", type=int)

    p = sub.add_parser("sync");   p.add_argument("--blue", type=int);  p.add_argument("--green", type=int)

    p = sub.add_parser("step");   p.add_argument("--blue", type=int, default=0); p.add_argument("--green", type=int, default=0)

    p = sub.add_parser("game");   p.add_argument("--state", choices=["start","stop","toggle"], default="toggle")

    p = sub.add_parser("set-step-delay"); p.add_argument("--value", type=float, required=True)

    args = ap.parse_args()

    payload = {"cmd": args.cmd.replace("-", "_")}
    if args.cmd in ("set","smooth","sync","step"):
        if args.blue  is not None: payload["blue"]  = args.blue
        if args.green is not None: payload["green"] = args.green
    if args.cmd == "game":
        payload["state"] = args.state
    if args.cmd == "set-step-delay":
        payload = {"cmd": "set_step_delay", "value": args.value}

    send(args.ip, args.port, payload)
