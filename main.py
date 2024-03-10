import time
import network
import socket
import machine
import ujson
import uasyncio
import ntptime

# SSID (name) and password of your WiFi network
SSID, PASSWORD = 'your SSID', 'your password'
# Port used for socket communication (default 7776)
PORT = 7776
# Enables logging to log.txt in root directory of Pico W
# For debugging purposes only, will eventually fill the board's 2 MB flash memory
ENABLE_LOGGING = False
# Enables setting system time from an NTP server for timestamped logging
ENABLE_SYSTEM_TIME = False
# Time zone offset from UTC (e.g. -5 for EST)
TIME_ZONE = -5
# Enables a 2 second rapid blink of the Pico W's onboard LED when receiving command to turn on PC
ENABLE_BLINKING = False
# Max time in seconds before restarting attempt to connect to WiFi
WIFI_TIMEOUT = 10
# Time in milliseconds that the relay is activated each time command is received
RELAY_TIME = 200
# Asynchronous coroutine will check for WiFi connection drop every CHECK_TIME seconds, set to 0 to disable
CHECK_TIME = 15

# Initialize WiFi functionality
wlan = network.WLAN(network.STA_IF)
wlan.active(True)

if ENABLE_LOGGING:
    log_file = open('log.txt', 'a')

if ENABLE_SYSTEM_TIME:
    time_is_set = False

socket_opened = False

def logger(*args, **kwargs):
    data = ' '.join(str(arg) for arg in args)

    if ENABLE_SYSTEM_TIME and time_is_set:
        data = to_iso8601(time.localtime(), TIME_ZONE, 0) + ': ' + data

    print(data)

    if ENABLE_LOGGING:
        log_file.write(data + '\n')
        log_file.flush()

async def attempt_connection(ssid, password):
    attempting_connection = True

    while attempting_connection:
        wlan.connect(ssid, password)
        
        logger('Waiting for WiFi connection...')

        wifi_timeout = WIFI_TIMEOUT
        while not wlan.isconnected() and wifi_timeout > 0:
            wifi_timeout -= 1
            await uasyncio.sleep(1)

        if wlan.isconnected():
            network_parameters = wlan.ifconfig()
            logger('Connection to', ssid, 'successfully established!', sep=' ')
            logger('Local IP address: ' + network_parameters[0])
            attempting_connection = False
        else:
            logger('Connection failed, reattempting...')
            await uasyncio.sleep(1)

async def check_connection(ssid, password):
    while True:
        if not ping():
            logger('WiFi connection dropped or network is offline. Attempting reconnection...')
            await attempt_connection(ssid, password)
        
        await uasyncio.sleep(CHECK_TIME)
    
def ping(host='8.8.8.8', port=53, timeout=3):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, port))
        s.close()
        return True
    except OSError as e:
        return False


async def blinkLED(led, seconds):
    for i in range(int(seconds * 10)):
        led.value(1)
        await uasyncio.sleep_ms(50)
        led.value(0)
        await uasyncio.sleep_ms(50)

def to_iso8601(local_time_tuple, tz_offset_hours=0, tz_offset_minutes=0):
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

async def main():
    try:
        logger('Beginning a new session')

        await attempt_connection(SSID, PASSWORD)

        if CHECK_TIME > 0:
            uasyncio.create_task(check_connection(SSID, PASSWORD))

        if ENABLE_SYSTEM_TIME:
            ntptime.settime()
            global time_is_set
            time_is_set = True
            logger('System time set!')
        
        relay = machine.Pin(2, machine.Pin.OUT)
        led = machine.Pin("LED", machine.Pin.OUT)

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setblocking(False)
        s.bind(('0.0.0.0', PORT))
        s.listen(1)
        global socket_opened
        socket_opened = True

        logger('Waiting for a socket connection...\n')

        # main loop
        while True:
            conn, addr, data, command = None, None, None, None

            try:
                conn, addr = s.accept()
            except OSError as e:
                if e.args[0] == 11: # EAGAIN
                    await uasyncio.sleep_ms(100)
                else:
                    raise
            
            if conn != None:
                logger('Connection from', addr)

                # Receive a command from the client
                while data == None:
                    try:
                        data = conn.recv(1024)
                        if data:
                            data = data.decode()
                            command = ujson.loads(data)
                    except OSError as e:
                        if e.args[0] == 11: # EAGAIN
                            await uasyncio.sleep_ms(100)
                        else:
                            raise

                # Excecute command to turn on PC
                if command != None:
                    if command['gpio'] == 'on':
                        logger('Command received!')
                        logger('Turning PC on...\n')

                        if ENABLE_BLINKING:
                            uasyncio.create_task(blinkLED(led, 2))

                        relay.value(1)
                        time.sleep_ms(RELAY_TIME)
                        relay.value(0)

                    else:
                        logger('Error reading data packet\n')

                conn.close()

    except Exception as e:
        logger('An error occurred: ' + str(e))
        logger('Ending session and restarting...\n\n')
        if ENABLE_LOGGING:
            log_file.close()
        if socket_opened:
            s.close()
        machine.reset()

uasyncio.run(main())
