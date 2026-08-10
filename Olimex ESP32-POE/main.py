import time
import errno
import network
import socket
import uselect
from machine import Pin, reset
import ujson
import uasyncio
import ntptime
import ubinascii
import uos
from micropython import const

# GPIO Pins used for relays and their corresponding ports used for socket communication (default 7776)
__RELAY_PORT1 = (Pin(32, Pin.OUT), const(7776))
__RELAY_PORT2 = (Pin(33, Pin.OUT), const(7775))
__RELAY_PORT3 = (Pin(4, Pin.OUT), const(7774))
# Optional external LED GPIO
# The 4 onboard LEDs are wired to the power rail and the Ethernet PHY, not to the ESP32,
# so none of them can be driven from code and blinking does nothing without an external LED
LED = Pin(13, Pin.OUT)
# Enables logging to log.txt in root directory of the board
# For testing/debugging purposes only, will eventually fill the board's 2 MB flash memory
ENABLE_LOGGING = const(False)
# Enables a 2 second rapid blink of the external LED when receiving command to turn on PC
ENABLE_BLINKING = const(False)
# Enables a daily forced reboot at REBOOT_TIME (hour 0-23) daily
ENABLE_REBOOTS = const(False)
REBOOT_TIME = const(5)
__REBOOT_RELAY = __RELAY_PORT1[0]
# Time zone offset from UTC (e.g. -5 for EST)
TIME_ZONE = const(-5)
# Enables correction for NA daylight savings time
# Assumes TIME_ZONE is set to standard time
CHECK_DST = const(True)
# Max time in seconds before restarting attempt to connect to network
NETWORK_TIMEOUT = const(10)
# Time in milliseconds that the relay is activated for power on command
SHORT_RELAY_TIME = const(200)
# Time in milliseconds that the relay is activated for force shutdown command
LONG_RELAY_TIME = const(7000)
# Will check for network connection drop every CHECK_TIME seconds, set to 0 to disable
CHECK_TIME = const(180)
# Max time in seconds to wait for a response when syncing time
NTP_TIMEOUT = const(5)

# Initialize network functionality
nic = network.LAN(
    0, mdc=Pin(23), mdio=Pin(18), power=Pin(12),
    phy_type=network.PHY_LAN8720, phy_addr=0,
    ref_clk=Pin(17), ref_clk_mode=Pin.OUT,
)
nic.active(True)

ntptime.timeout = NTP_TIMEOUT

if ENABLE_LOGGING:
    log_file = open('log.txt', 'a')

time_is_set = False
sockets_opened = False
in_dst = False

def _logger(*args):
    data = ' '.join(str(arg) for arg in args)

    if time_is_set:
        data = _iso8601_time() + ': ' + data

    print(data)

    if ENABLE_LOGGING:
        log_file.write(data + '\n')
        log_file.flush()

async def attempt_connection():
    attempting_connection = True

    while attempting_connection:
        # Bouncing the interface restarts DHCP, ifconfig('dhcp') raises 0x5004 since active(True) already started it
        nic.active(False)
        await uasyncio.sleep(1)
        nic.active(True)

        _logger("Waiting for network connection...")

        network_timeout = NETWORK_TIMEOUT
        while not nic.isconnected() and network_timeout > 0:
            network_timeout -= 1
            await uasyncio.sleep(1)

        if nic.isconnected():
            network_parameters = nic.ifconfig()
            mac = ubinascii.hexlify(nic.config('mac'), ':').decode()
            _logger("Connection to network successfully established!")
            _logger(f"Local IP address: {network_parameters[0]}")
            _logger(f"MAC Address: {mac}")
            attempting_connection = False
        else:
            _logger("Connection failed, reattempting...")
            await uasyncio.sleep(1)

async def check_connection():
    while True:
        await uasyncio.sleep(CHECK_TIME)

        if not await _ping():
            _logger("Network connection dropped, attempting reconnection...")
            await attempt_connection()
    
async def _ping(host='8.8.8.8', port=53, timeout=3):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setblocking(False)
        addr = socket.getaddrinfo(host, port)[0][-1]
        try:
            sock.connect(addr)
        except OSError as e:
            # A non-blocking connect reports EINPROGRESS instead of completing here
            if e.args[0] != errno.EINPROGRESS:
                return False
        poller = uselect.poll()
        poller.register(sock, uselect.POLLOUT)
        for _ in range(int(timeout * 10)):
            events = poller.poll(0)
            if events:
                return not (events[0][1] & (uselect.POLLERR | uselect.POLLHUP))
            await uasyncio.sleep_ms(100)
        return False
    except OSError:
        return False
    finally:
        sock.close()
    
def _get_socket(ip='0.0.0.0', port=7776):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setblocking(False)
    sock.bind((ip, port))
    sock.listen(1)
    return sock

async def _blinkLED(led, seconds):
    for i in range(int(seconds * 10)):
        led.value(1)
        await uasyncio.sleep_ms(50)
        led.value(0)
        await uasyncio.sleep_ms(50)

def _check_dst():
    year, month, mday, _, _, _, _, _ = _get_localtime()

    def _weekday(year, month, day):
        if month < 3:
            month += 12
            year -= 1
        k = year % 100
        j = year // 100
        h = (day + (13 * (month + 1)) // 5 + k + k // 4 + j // 4 + 5 * j) % 7
        return (h + 5) % 7
    
    # Find second Sunday in March
    mar1_wd = _weekday(year, 3, 1)
    second_sun_mar = 1 + ((6 - mar1_wd) % 7) + 7

    # Find first Sunday in November
    nov1_wd = _weekday(year, 11, 1)
    first_sun_nov = 1 + ((6 - nov1_wd) % 7)

    # Determine if DST is active
    global in_dst
    if 3 < month < 11:
        in_dst = True
    elif month == 3 and mday >= second_sun_mar:
        in_dst = True
    elif month == 11 and mday < first_sun_nov:
        in_dst = True
    else:
        in_dst = False

def _get_localtime():
    tz = TIME_ZONE
    if in_dst:
        tz += 1

    return time.localtime(time.time() + (tz * 3600))

def _iso8601_time():
    year, month, day, hour, minute, second, _, _ = _get_localtime()
    return "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}".format(year, month, day, hour, minute, second)

async def power_on(relay):
    _logger("Turning PC on...\n")

    relay.value(1)
    await uasyncio.sleep_ms(SHORT_RELAY_TIME)
    relay.value(0)

async def force_shutdown(relay):
    _logger("Shutting off PC...\n")

    relay.value(1)
    await uasyncio.sleep_ms(LONG_RELAY_TIME)
    relay.value(0)

async def _run_command(gpio, relay, lock, queue):
    if lock.locked():
        _logger("Busy, command queued...\n")

    try:
        async with lock:
            if gpio == 'on':
                await power_on(relay)
            else:
                await force_shutdown(relay)
    finally:
        queue[0] -= 1

async def daily_task(reboot_relay=None):
    while True:
        current_time = _get_localtime()

        if (current_time[3] == REBOOT_TIME and current_time[4] == 0):
            if ENABLE_REBOOTS:
                _logger("Performing scheduled forced reboot...")

                await force_shutdown(reboot_relay)
                await uasyncio.sleep(3)
                await power_on(reboot_relay)

            _logger("Syncing RTC...")

            try:
                ntptime.settime()
                if CHECK_DST:
                    _check_dst()
                _logger("Synced!")
            except OSError as e:
                _logger("Failed to sync RTC: {}".format(e))
            await uasyncio.sleep(3600)
        else:
            await uasyncio.sleep(30)

async def receive_command(socket, relay, port):
    # Serializes relay actions on this port, at most one command waits behind the running one
    lock = uasyncio.Lock()
    # Running command plus the queued one
    queue = [0]

    while True:
        conn, addr, data, command = None, None, None, None

        try:
            conn, addr = socket.accept()
        except OSError as e:
            if e.args[0] == errno.EAGAIN:
                await uasyncio.sleep_ms(100)
            else:
                raise
        
        if conn != None:
            _logger("Connection on {} from {}".format(port, addr))

            conn.settimeout(3)
            # Receive a command from the client
            while True:
                try:
                    data = conn.recv(1024)
                    if data != None:
                        try:
                            data = data.decode()
                            command = ujson.loads(data)
                            break
                        except ValueError as e:
                            _logger("Invalid JSON received: {}".format(e))
                            break
                    else:
                        await uasyncio.sleep_ms(100)

                except OSError as e:
                    if e.args[0] == errno.ETIMEDOUT:
                        _logger("Connection timed out, closing...\n")
                        break
                    if e.args[0] == errno.EAGAIN:
                        await uasyncio.sleep_ms(100)
                    else:
                        raise

            # Excecute command to turn on PC
            if command != None:
                _logger("Command received!")

                if ENABLE_BLINKING:
                        uasyncio.create_task(_blinkLED(LED, 2))

                gpio = command.get('gpio')
                if gpio != 'on' and gpio != 'fs':
                    status = 'error'
                    _logger("Error reading command\n")
                elif queue[0] >= 2:
                    status = 'full'
                    _logger("Busy, command queue full...\n")
                else:
                    status = 'ack'
                    queue[0] += 1
                    uasyncio.create_task(_run_command(gpio, relay, lock, queue))

                try:
                    conn.sendall(ujson.dumps({'status': status}) + '\n')
                except OSError as e:
                    _logger("Failed to send acknowledgement: {}".format(e))

            conn.close()

async def sync_time():
    global time_is_set

    while True:
        try:
            ntptime.settime()
            if CHECK_DST:
                _check_dst()
            time_is_set = True
            _logger("System time set!\n")
            return
        except OSError as e:
            _logger("Failed to sync time, retrying: {}".format(e))
            await uasyncio.sleep(10)

async def main():
    try:
        _logger("Beginning a new session")
        _logger("Board: {} {}".format(uos.uname().machine, '(wired)'))

        await attempt_connection()

        if CHECK_TIME > 0:
            uasyncio.create_task(check_connection())

        s1 = _get_socket(port=__RELAY_PORT1[1])
        s2 = _get_socket(port=__RELAY_PORT2[1])
        s3 = _get_socket(port=__RELAY_PORT3[1])
        global sockets_opened
        sockets_opened = True

        _logger("Waiting for a socket connection...\n")

        uasyncio.create_task(receive_command(s1, *__RELAY_PORT1))
        uasyncio.create_task(receive_command(s2, *__RELAY_PORT2))
        uasyncio.create_task(receive_command(s3, *__RELAY_PORT3))
        uasyncio.create_task(daily_task(__REBOOT_RELAY))
        uasyncio.create_task(sync_time())

        while True:
            await uasyncio.sleep(180)

    except Exception as e:
        _logger("An error occurred: " + str(e))
        _logger("Ending session and restarting...\n\n")
        if ENABLE_LOGGING:
            log_file.close()
        if sockets_opened:
            s1.close()
            s2.close()
            s3.close()
        reset()

if __name__ == "__main__":
    uasyncio.run(main())
