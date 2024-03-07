from time import sleep, sleep_ms
import network
import socket
import machine
import ujson

# SSID (name) and password of your WiFi network
SSID, PASSWORD = 'your SSID', 'your password'
# Port used for socket communication (default 7776)
PORT = 7776
# Enables logging to log.txt in root directory of Pico W
# For debugging purposes only, will eventually fill the board's 2 MB flash memory
ENABLE_LOGGING = False
# Enables a 2 second rapid blink of the Pico W's onboard LED when receiving command to turn on PC
# For testing purposes only, relay won't activate until LED is done blinking
ENABLE_BLINKING = False
# Max time in seconds before restarting attempt to connect to WiFi
# Reattempt will happen sooner if connection fails for another reason
WIFI_TIMEOUT = 10
# Time in milliseconds that the relay is activated each time command is received
RELAY_TIME = 200

if ENABLE_LOGGING:
        log_file = open('log.txt', 'a')

def logger(*args, **kwargs):
    data = ' '.join(str(arg) for arg in args)
    print(data)
    if ENABLE_LOGGING:
        log_file.write(data + '\n')
        log_file.flush()

def attempt_connection(ssid, password):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(ssid, password)
    
    logger('Waiting for WiFi connection...')

    for i in range(WIFI_TIMEOUT):
        # wlan.status() < 0 means connection failed for some reason
        # wlan.status () == 3 means connection successful
        if wlan.status() < 0 or wlan.status() == 3:
            break
        sleep(1)

    if wlan.status() == 3:
        network_parameters = wlan.ifconfig()
        logger('Connection to', ssid, 'successfully established!', sep=' ')
        logger('Local IP address: ' + network_parameters[0])
        return False
    else:
        logger('Connection failed, reattempting...')
        sleep(1)
        return True

def blinkLED(led, seconds):
    for i in range(int(seconds * 10)):
        led.value(1)
        sleep_ms(50)
        led.value(0)
        sleep_ms(50)

# main thread
try:
    logger('Beginning a new session')

    attempting_connection = True
    while attempting_connection:
        attempting_connection = attempt_connection(SSID, PASSWORD)

    relay = machine.Pin(2, machine.Pin.OUT)
    led = machine.Pin("LED", machine.Pin.OUT)

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('0.0.0.0', PORT))
    s.listen(1)

    # main loop
    while True:
        logger('Waiting for a socket connection...\n')
        conn, addr = s.accept()
        logger('Connection from', addr)

        # Receive a command from the client
        data = conn.recv(1024).decode()
        command = ujson.loads(data)
        logger('Command received: ', command)

        # Turn the GPIO pin on or off based on the received command
        if command['gpio'] == 'on':
            logger('Turning PC on...\n')

            if ENABLE_BLINKING:
                blinkLED(led, 2)

            relay.value(1)
            sleep_ms(RELAY_TIME)
            relay.value(0)

        else:
            logger('Error reading data packet\n')
        conn.close()

except Exception as e:
    logger('An error occurred: ' + str(e))
    logger('Ending session and restarting...\n\n')
    if ENABLE_LOGGING:
        log_file.close()
    s.close()
    machine.reset()
