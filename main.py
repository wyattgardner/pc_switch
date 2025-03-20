import time
import network
import socket
from machine import Pin, SPI, reset
import ujson
import uasyncio
import ntptime
import ubinascii
from micropython import const

# Toggles between wireless (WiFi) and wired (Ethernet) mode
# Set to true for Pico W and false for W5500-EVB-Pico
WIRELESS_MODE = const(True)
# SSID (name) and password of your WiFi network
__SSID, __PASSWORD = const('your SSID'), const('your password')
# GPIO Pins used for relays and their corresponding ports used for socket communication (default 7776)
__RELAY_PORT1 = (Pin(2, Pin.OUT), const(7776))
__RELAY_PORT2 = (Pin(3, Pin.OUT), const(7775))
__RELAY_PORT3 = (Pin(4, Pin.OUT), const(7774))
# Onboard LED GPIO
LED = Pin(25, Pin.OUT)
# Enables logging to log.txt in root directory of Pico W
# For testing/debugging purposes only, will eventually fill the board's 2 MB flash memory
ENABLE_LOGGING = const(False)
# Enables a 2 second rapid blink of the Pico W's onboard LED when receiving command to turn on PC
ENABLE_BLINKING = const(False)
# Enables a daily forced reboot at REBOOT_TIME (hour 0-23) daily
ENABLE_REBOOTS = const(False)
REBOOT_TIME = const(4)
__REBOOT_RELAY = __RELAY_PORT2[0]
# Time zone offset from UTC (e.g. -5 for EST)
TIME_ZONE = const(-5)
# Max time in seconds before restarting attempt to connect to network
NETWORK_TIMEOUT = const(10)
# Time in milliseconds that the relay is activated for power on command
SHORT_RELAY_TIME = const(200)
# Time in milliseconds that the relay is activated for force shutdown command
LONG_RELAY_TIME = const(7000)
# Will check for WiFi connection drop every CHECK_TIME seconds, set to 0 to disable
CHECK_TIME = const(180)

# Initialize network functionality
if WIRELESS_MODE:
    nic = network.WLAN(network.STA_IF)
    nic.active(True)
    nic.config(pm = 0xa11140) # Disable power saving mode
else:
    spi = SPI(0, 2_000_000, mosi=Pin(19), miso=Pin(16), sck=Pin(18))
    nic = network.WIZNET5K(spi, Pin(17), Pin(20)) #spi, cs, reset pin
    nic.active(True)

if ENABLE_LOGGING:
    log_file = open('log.txt', 'a')

time_is_set = False
sockets_opened = False

def _logger(*args):
    data = ' '.join(str(arg) for arg in args)

    if time_is_set:
        data = _to_iso8601(_get_localtime()) + ': ' + data

    print(data)

    if ENABLE_LOGGING:
        log_file.write(data + '\n')
        log_file.flush()

async def attempt_connection():
    attempting_connection = True

    while attempting_connection:
        if WIRELESS_MODE:
            nic.connect(__SSID, __PASSWORD)
        else:
            nic.ifconfig('dhcp')
        
        _logger('Waiting for network connection...')

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
            _logger('Connection failed, reattempting...')
            await uasyncio.sleep(1)

async def check_connection():
    while True:
        await uasyncio.sleep(CHECK_TIME)

        if not _ping():
            _logger('Network connection dropped, attempting reconnection...')
            await attempt_connection()
    
def _ping(host='8.8.8.8', port=53, timeout=3):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, port))
        s.close()
        return True
    except OSError as e:
        return False
    
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

def _to_iso8601(time_tuple):
    year, month, day, hour, minute, second, _, _ = time_tuple
    return "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}".format(year, month, day, hour, minute, second)

def _get_localtime():
    return time.localtime(time.time() + (TIME_ZONE * 3600))

async def power_on(relay):
    _logger('Turning PC on...\n')

    relay.value(1)
    await uasyncio.sleep_ms(SHORT_RELAY_TIME)
    relay.value(0)

async def force_shutdown(relay):
    _logger('Shutting off PC...\n')

    relay.value(1)
    await uasyncio.sleep_ms(LONG_RELAY_TIME)
    relay.value(0)

async def scheduled_reboot(relay):
    while True:
        current_time = _get_localtime()

        if (current_time[3] == REBOOT_TIME and current_time[4] == 0):
            _logger("Performing scheduled forced reboot...")

            await force_shutdown(relay)
            await uasyncio.sleep(3)
            await power_on(relay)
            await uasyncio.sleep(3600)
        else:
            await uasyncio.sleep(30)

async def receive_command(socket, relay, port):
    while True:
        conn, addr, data, command = None, None, None, None

        try:
            conn, addr = socket.accept()
        except OSError as e:
            if e.args[0] == 11: # EAGAIN
                await uasyncio.sleep_ms(100)
            else:
                raise
        
        if conn != None:
            _logger('Connection on {} from {}'.format(port, addr))

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
                            _logger('Invalid JSON received: {}'.format(e))
                            break
                    else:
                        await uasyncio.sleep_ms(100)

                except OSError as e:
                    if e.args[0] == 110: # ETIMEDOUT
                        _logger('Connection timed out, closing...\n')
                        break
                    if e.args[0] == 11: # EAGAIN
                        await uasyncio.sleep_ms(100)
                    else:
                        raise

            # Excecute command to turn on PC
            if command != None:
                _logger('Command received!')

                if ENABLE_BLINKING:
                        uasyncio.create_task(_blinkLED(LED, 2))

                if command['gpio'] == 'on':
                    await power_on(relay)

                elif command['gpio'] == 'fs':
                    await force_shutdown(relay)
                    
                else:
                    _logger('Error reading command\n')

            conn.close()

async def main():
    try:
        _logger('Beginning a new session')

        await attempt_connection()

        if CHECK_TIME > 0:
            uasyncio.create_task(check_connection())

        ntptime.settime()
        global time_is_set
        time_is_set = True
        _logger('System time set!')

        s1 = _get_socket(port=__RELAY_PORT1[1])
        s2 = _get_socket(port=__RELAY_PORT2[1])
        s3 = _get_socket(port=__RELAY_PORT3[1])
        global sockets_opened
        sockets_opened = True

        _logger('Waiting for a socket connection...\n')

        uasyncio.create_task(receive_command(s1, *__RELAY_PORT1))
        uasyncio.create_task(receive_command(s2, *__RELAY_PORT2))
        uasyncio.create_task(receive_command(s3, *__RELAY_PORT3))
        if ENABLE_REBOOTS:
            uasyncio.create_task(scheduled_reboot(__REBOOT_RELAY))

        while True:
            await uasyncio.sleep(180)

    except Exception as e:
        _logger('An error occurred: ' + str(e))
        _logger('Ending session and restarting...\n\n')
        if ENABLE_LOGGING:
            log_file.close()
        if sockets_opened:
            s1.close()
            s2.close()
            s3.close()
        reset()

if __name__ == "__main__":
    uasyncio.run(main())
