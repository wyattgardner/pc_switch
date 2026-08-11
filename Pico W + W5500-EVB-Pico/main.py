import time
import errno
import network
import socket
import uselect
from machine import Pin, SPI, reset
import ujson
import uasyncio
import ntptime
import ubinascii
import uos
from micropython import const

# Toggles between wireless (WiFi) and wired (Ethernet) mode
# Set to true for Pico W and false for W5500-EVB-Pico
WIRELESS_MODE = const(True)
# SSID (name) and password of your WiFi network
__SSID, __PASSWORD = const('your SSID'), const('your password')
# GPIO pins used for relays and their corresponding ports used for socket communication (default 7776)
# Add or remove (GPIO, port) pairs to serve any number of relays
__RELAY_ASSIGNMENTS = ((2, 7776), (3, 7775), (4, 7774))
# Onboard LED GPIO
LED = Pin(25, Pin.OUT)
# Enables logging to log.txt in root directory of Pico W
# For testing/debugging purposes only, will eventually fill the board's 2 MB flash memory
ENABLE_LOGGING = const(False)
# Enables a 2 second rapid blink of the Pico W's onboard LED when receiving command to turn on PC
ENABLE_BLINKING = const(False)
# Enables a daily forced reboot at REBOOT_TIME (hour 0-23) daily
ENABLE_REBOOTS = const(False)
REBOOT_TIME = const(5)
# Relay the forced reboot acts on, as an index into __RELAY_ASSIGNMENTS
__REBOOT_RELAY_INDEX = const(0)
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
# Attempts each RTC sync makes before giving up, and seconds between them
SYNC_ATTEMPTS = const(5)
SYNC_RETRY_TIME = const(10)

# Initialize network functionality
if WIRELESS_MODE:
    nic = network.WLAN(network.STA_IF)
    # Clears any association left over from a soft reset
    nic.active(False)
    time.sleep(1)
    nic.active(True)
    nic.config(pm = 0xa11140) # Disable power saving mode
else:
    spi = SPI(0, 2_000_000, mosi=Pin(19), miso=Pin(16), sck=Pin(18))
    nic = network.WIZNET5K(spi, Pin(17), Pin(20)) #spi, cs, reset pin
    nic.active(True)

ntptime.timeout = NTP_TIMEOUT

if ENABLE_LOGGING:
    log_file = open('log.txt', 'a')

time_is_set = False
in_dst = False
# One listening socket per relay, filled in by main()
sockets = []

def _logger(*args):
    data = ' '.join(str(arg) for arg in args)

    if time_is_set:
        data = _iso8601_time() + ': ' + data

    print(data)

    if ENABLE_LOGGING:
        log_file.write(data + '\n')
        log_file.flush()

def _relays(*assignments):
    # Each assignment is a (GPIO, port) pair, one listening socket is opened per relay
    relays = tuple((Pin(gpio, Pin.OUT, value=0), port) for gpio, port in assignments)

    _logger("Relays initialized: " + ', '.join("GPIO{} on port {}".format(gpio, port) for gpio, port in assignments))

    return relays

__RELAYS = _relays(*__RELAY_ASSIGNMENTS)

async def _attempt_connection():
    attempting_connection = True

    while attempting_connection:
        if WIRELESS_MODE:
            nic.connect(__SSID, __PASSWORD)
        else:
            nic.ifconfig('dhcp')
        
        _logger("Waiting for network connection...")

        network_timeout = NETWORK_TIMEOUT
        while not nic.isconnected() and network_timeout > 0:
            network_timeout -= 1
            await uasyncio.sleep(1)

        if nic.isconnected():
            network_parameters = nic.ifconfig()
            mac = ubinascii.hexlify(nic.config('mac'), ':').decode()
            _logger(f"Connection to {__SSID if WIRELESS_MODE else 'network'} successfully established!")
            _logger(f"Local IP address: {network_parameters[0]}")
            _logger(f"MAC Address: {mac}")
            attempting_connection = False
        else:
            if WIRELESS_MODE:
                _logger("Connection failed (status {}), reattempting...".format(nic.status()))
            else:
                _logger("Connection failed, reattempting...")
            await uasyncio.sleep(1)

async def _check_connection():
    while True:
        await uasyncio.sleep(CHECK_TIME)

        if not await _ping():
            _logger("Network connection dropped, attempting reconnection...")
            await _attempt_connection()
    
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

async def blink_LED(led, seconds):
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

            await sync_time(SYNC_ATTEMPTS)

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
                        uasyncio.create_task(blink_LED(LED, 2))

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

async def sync_time(attempts=0):
    # An attempts of 0 keeps retrying until the sync succeeds
    global time_is_set

    attempt = 0

    while True:
        attempt += 1

        try:
            ntptime.settime()
            if CHECK_DST:
                _check_dst()
            time_is_set = True
            _logger("System time set!\n")
            return True
        except OSError as e:
            if attempts and attempt >= attempts:
                _logger("Failed to sync time after {} attempts: {}\n".format(attempt, e))
                return False

            _logger("Failed to sync time, retrying: {}".format(e))
            await uasyncio.sleep(SYNC_RETRY_TIME)

async def main():
    try:
        _logger("Beginning a new session")
        _logger("Board: {} {}".format(uos.uname().machine, '(wireless)' if WIRELESS_MODE else '(wired)'))

        await _attempt_connection()

        if CHECK_TIME > 0:
            uasyncio.create_task(_check_connection())

        for _, port in __RELAYS:
            sockets.append(_get_socket(port=port))

        _logger("Waiting for a socket connection...\n")

        for sock, (relay, port) in zip(sockets, __RELAYS):
            uasyncio.create_task(receive_command(sock, relay, port))
        uasyncio.create_task(daily_task(__RELAYS[__REBOOT_RELAY_INDEX][0]))
        uasyncio.create_task(sync_time(SYNC_ATTEMPTS))

        while True:
            await uasyncio.sleep(180)

    except Exception as e:
        _logger("An error occurred: " + str(e))
        _logger("Ending session and restarting...\n\n")
        if ENABLE_LOGGING:
            log_file.close()
        for sock in sockets:
            sock.close()
        reset()

if __name__ == "__main__":
    uasyncio.run(main())
