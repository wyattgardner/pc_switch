# Sends a command to a pc_switch board, defaults to the reboot_board command that applies a main.py pushed over WebREPL

import argparse
import json
import socket

# Port to send to when one is not given, the first relay's port
DEFAULT_PORT = 7776
# Seconds to wait for the board to acknowledge
TIMEOUT = 5
# Seconds to wait for the board to report a queued command starting, which only happens once the
# command ahead of it has released the relay
QUEUED_TIMEOUT = 30

def send_command(host, command='reboot_board', port=DEFAULT_PORT, timeout=TIMEOUT):
    """
    Sends a single request to a board and returns its response as a string.

    A queued command gets a second response once it starts running, so both are returned
    separated by an arrow.
    """
    sock = socket.socket()
    sock.settimeout(timeout)

    try:
        sock.connect((host, port))
        sock.sendall(json.dumps({'request': command}).encode())
        response = sock.recv(128).decode().strip()

        try:
            queued = json.loads(response).get('response') == 'queued'
        except ValueError:
            # Anything unparseable is passed straight back to the caller to look at
            queued = False

        if not queued:
            return response

        print(f"{response} -> waiting for the running command to finish...")
        sock.settimeout(QUEUED_TIMEOUT)
        return response + ' -> ' + sock.recv(128).decode().strip()
    finally:
        sock.close()

def main():
    parser = argparse.ArgumentParser(description="Send a command to a pc_switch board.")
    parser.add_argument('host', help="LAN address of the board")
    parser.add_argument('command', nargs='?', default='reboot_board',
                        help="'reboot_board' to restart the board, 'turn_pc_on' to power on, 'force_shutdown_pc' to force shutdown (default: reboot_board)")
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
