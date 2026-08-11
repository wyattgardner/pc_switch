import webrepl
from micropython import const

# Enables WebREPL, which serves a REPL and file transfers on port 8266
# Lets main.py be updated over the network instead of over USB, see the README
ENABLE_WEBREPL = const(True)
# WebREPL password, must be 4 to 9 characters
__WEBREPL_PASSWORD = const('admin')

if ENABLE_WEBREPL:
    # Binds before the network is up, lwIP starts accepting once main.py has an address
    webrepl.start(password=__WEBREPL_PASSWORD)
