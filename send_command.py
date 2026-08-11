# Sends a command to a pc_switch board, defaults to the reboot_board command that applies a main.py pushed over WebREPL

import argparse
import json
import socket

# Port to send to when one is not given, the first relay's port
DEFAULT_PORT = 7776
# Seconds to wait for the board to acknowledge
TIMEOUT = 5

def send_command(host, command='reboot_board', port=DEFAULT_PORT, timeout=TIMEOUT):
    """
    Sends a single JSON command to a board and returns its acknowledgement as a string.
    """
    sock = socket.socket()
    sock.settimeout(timeout)

    try:
        sock.connect((host, port))
        sock.sendall(json.dumps({'gpio': command}).encode())
        return sock.recv(128).decode().strip()
    finally:
        sock.close()

def main():
    parser = argparse.ArgumentParser(description="Send a command to a pc_switch board.")
    parser.add_argument('host', help="LAN address of the board")
    parser.add_argument('command', nargs='?', default='reboot_board',
                        help="'reboot_board' to restart the board, 'on' to power on, 'fs' to force shutdown (default: reboot_board)")
    parser.add_argument('-p', '--port', type=int, default=DEFAULT_PORT,
                        help="port the target relay listens on (default: {})".format(DEFAULT_PORT))
    args = parser.parse_args()

    print(f"Sending '{args.command}' to {args.host}:{args.port}...")

    try:
        print(send_command(args.host, args.command, args.port))
    except OSError as e:
        raise SystemExit(f"Failed to reach the board: {e}")

if __name__ == "__main__":
    main()
