import time
import network
import socket
import machine
import ujson
import uasyncio
import ntptime
import ubinascii
from micropython import const

# SSID (name) and password of your WiFi network
__SSID, __PASSWORD = const('your SSID'), const('your password')
# Ports used for socket communication (default 7776)
__PORT1 = const(7776)
__PORT2 = const(7775)
# GPIO Pins used for relays and onboard LED
RELAY1 = machine.Pin(2, machine.Pin.OUT)
RELAY2 = machine.Pin(3, machine.Pin.OUT)
LED = machine.Pin("LED", machine.Pin.OUT)
# Enables logging to log.txt in root directory of Pico W
# For testing/debugging purposes only, will eventually fill the board's 2 MB flash memory
ENABLE_LOGGING = const(False)
# Enables setting system time from an NTP server for timestamped logging
ENABLE_SYSTEM_TIME = const(False)
# Enables a 2 second rapid blink of the Pico W's onboard LED when receiving command to turn on PC
ENABLE_BLINKING = const(False)
# Time zone offset from UTC (e.g. -5 for EST)
TIME_ZONE = const(-4)
# Max time in seconds before restarting attempt to connect to WiFi
WIFI_TIMEOUT = const(10)
# Time in milliseconds that the relay is activated for power on command
SHORT_RELAY_TIME = const(200)
# Time in milliseconds that the relay is activated for force shutdown command
LONG_RELAY_TIME = const(7000)
# Asynchronous coroutine will check for WiFi connection drop every CHECK_TIME seconds, set to 0 to disable
CHECK_TIME = const(180)

# Initialize WiFi functionality
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.config(pm = 0xa11140) # Disable power saving mode

if ENABLE_LOGGING:
    log_file = open('log.txt', 'a')

if ENABLE_SYSTEM_TIME:
    time_is_set = False

sockets_opened = False

def _logger(*args, **kwargs):
    data = ' '.join(str(arg) for arg in args)

    if ENABLE_SYSTEM_TIME and time_is_set:
        data = _to_iso8601(time.localtime(), TIME_ZONE, 0) + ': ' + data

    print(data)

    if ENABLE_LOGGING:
        log_file.write(data + '\n')
        log_file.flush()

async def attempt_connection(ssid, password):
    attempting_connection = True

    while attempting_connection:
        wlan.connect(ssid, password)
        
        _logger('Waiting for WiFi connection...')

        wifi_timeout = WIFI_TIMEOUT
        while not wlan.isconnected() and wifi_timeout > 0:
            wifi_timeout -= 1
            await uasyncio.sleep(1)

        if wlan.isconnected():
            network_parameters = wlan.ifconfig()
            _logger('Connection to', ssid, 'successfully established!', sep=' ')
            _logger('Local IP address: ' + network_parameters[0])
            _logger('MAC address: ' + ubinascii.hexlify(network.WLAN().config('mac'), ':').decode())
            attempting_connection = False
        else:
            _logger('Connection failed, reattempting...')
            await uasyncio.sleep(1)

async def check_connection(ssid, password):
    while True:
        if not _ping():
            _logger('WiFi connection dropped or network is offline. Attempting reconnection...')
            await attempt_connection(ssid, password)
        
        await uasyncio.sleep(CHECK_TIME)
    
def _ping(host='8.8.8.8', port=53, timeout=3):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, port))
        s.close()
        return True
    except OSError as e:
        return False


async def _blinkLED(led, seconds):
    for i in range(int(seconds * 10)):
        led.value(1)
        await uasyncio.sleep_ms(50)
        led.value(0)
        await uasyncio.sleep_ms(50)

def _to_iso8601(local_time_tuple, tz_offset_hours=0, tz_offset_minutes=0):
    # Adjust hours and minutes for timezone offset
    year, month, day, hour, minute, second, _, _ = local_time_tuple
    hour += tz_offset_hours
    minute += tz_offset_minutes
    
    # Handle overflow/underflow in hours and minutes
    if minute >= 60:
        hour += 1
        minute -= 60
    elif minute < 0:
        hour -= 1
        minute += 60
    # Increment or decrement day, not handling month/year rollover for brevity
    if hour >= 24:
        day += 1
        hour -= 24
    elif hour < 0:
        day -= 1 
        hour += 24
    
    return "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}".format(year, month, day, hour, minute, second)

async def receive_command(relay, socket, port):
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
                    _logger('Turning PC on...\n')

                    relay.value(1)
                    await uasyncio.sleep_ms(SHORT_RELAY_TIME)
                    relay.value(0)

                elif command['gpio'] == 'fs':
                    _logger('Shutting off PC...\n')

                    relay.value(1)
                    await uasyncio.sleep_ms(LONG_RELAY_TIME)
                    relay.value(0)
                    
                else:
                    _logger('Error reading command\n')

            conn.close()

async def main():
    try:
        _logger('Beginning a new session')

        await attempt_connection(__SSID, __PASSWORD)

        if CHECK_TIME > 0:
            uasyncio.create_task(check_connection(__SSID, __PASSWORD))

        if ENABLE_SYSTEM_TIME:
            ntptime.settime()
            global time_is_set
            time_is_set = True
            _logger('System time set!')

        s1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s1.setblocking(False)
        s1.bind(('0.0.0.0', __PORT1))
        s1.listen(1)
        s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s2.setblocking(False)
        s2.bind(('0.0.0.0', __PORT2))
        s2.listen(1)
        global sockets_opened
        sockets_opened = True

        _logger('Waiting for a socket connection...\n')

        uasyncio.create_task(receive_command(RELAY1, s1, __PORT1))
        uasyncio.create_task(receive_command(RELAY2, s2, __PORT2))

        while True:
            await uasyncio.sleep(1)

    except Exception as e:
        _logger('An error occurred: ' + str(e))
        _logger('Ending session and restarting...\n\n')
        if ENABLE_LOGGING:
            log_file.close()
        if sockets_opened:
            s1.close()
            s2.close()
        machine.reset()

if __name__ == "__main__":
    uasyncio.run(main())
