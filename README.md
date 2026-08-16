# pc_switch
MicroPython project to turn on a PC over the internet

Credit to [Lutz](https://www.youtube.com/watch?v=znwLqv2otRQ)

Supported boards, each with its own folder in this repository:
- [Raspberry Pi Pico W](#raspberry-pi-pico-w) (WiFi)
- [W5500-EVB-Pico](#w5500-evb-pico) (Ethernet)
- [Olimex ESP32-POE](#olimex-esp32-poe) (Ethernet with Power over Ethernet)

# Required Parts
- One of the supported boards (see its section below for board specific parts)
- Jumper wire splitter ([what I used](https://www.amazon.com/gp/product/B0CNYJZ8D7/))
- 3.3V Relay ([what I used](https://www.amazon.com/gp/product/B08W3XDNGK/?th=1))
- At least 5 Male to Female jumper wires (need more to run wire outside of PC case)

# Setup
1. Flash MicroPython onto your board, see your board's section below for the firmware it needs.
2. Open main.py in your board's folder and set the options at the top. On the Pico W that includes your network's SSID and password.
3. Upload main.py to the root directory of the board (methods include the [Thonny editor](https://projects.raspberrypi.org/en/projects/getting-started-with-the-pico/9), the MicroPico extension in VS Code, or `mpremote fs cp main.py :main.py`). Optionally upload boot.py from this repository's root alongside it, which turns on [WebREPL](#updating-over-the-network).
4. Disconnect power button wires from power button pins on your PC's motherboard.
5. Connect a jumper wire splitter to the pins and reconnect the power button wires to one end of the splitter.
6. On the other end of the splitter, run two jumper wires to the NO and COM pins of the relay.
7. Use jumper wires to connect the board's relay GPIO to the relay's IN pin, a 3.3V pin to the relay's VCC pin, and a GND pin to the relay's GND pin. The GPIOs each board uses are listed in its section below.
8. Power the board to start the program.
9. Figure out the LAN address assigned to the board. You could look at your network gateway's UI or view the program's output over a MicroPython REPL connection (e.g. MicroPico).
10. Enter the LAN address into the [accompanying Android app](https://github.com/wyattgardner/pc_switch_app).
    * To use your network's WAN address to send the packet, you must forward the port you're using (7776 by default) to the board.
11. You can now use the app to turn on your PC.

# Requests and responses
The board speaks a small JSON protocol over TCP. Open a connection to a relay's port, send one request, and read the response. Every message is a single JSON object.

A request names what you want the board to do:

```json
{"request": "turn_pc_on"}
```

| Request | Does |
| --- | --- |
| `turn_pc_on` | Taps the relay briefly to press the power button |
| `force_shutdown_pc` | Holds the relay down to force a shutdown |
| `reboot_board` | Restarts the board itself, used to apply an updated main.py |

The board answers with a response and, for `reboot_board`, restarts right after sending it:

```json
{"response": "ack"}
```

| Response | Means |
| --- | --- |
| `ack` | Request accepted and being carried out now |
| `queued` | Request accepted but waiting behind the running command |
| `error` | Request was missing or not one of the three above |
| `full` | A command is already running with another queued, so this one was dropped |

Each relay listens on its own port and handles one request at a time, queueing at most one behind the running command.

A `queued` reply is the one case where the connection stays open. The board holds it until the command ahead has released the relay, then sends a second object as the queued command starts and closes:

```json
{"response": "running"}
```

`running` marks the same moment for a queued command that `ack` marks for one that runs immediately: the board is about to move the relay, not finished with it. That keeps a client's timing consistent whichever reply it got.

Reading that second object is optional, a client that closes after `queued` just misses it. Since it can arrive several seconds later (a force shutdown ahead of it holds the relay for `LONG_RELAY_TIME`), give the second read a longer timeout than the first.

send_command.py sends any of these, and the [Android app](https://github.com/wyattgardner/pc_switch_app) sends `turn_pc_on` and `force_shutdown_pc`.

send_command.py usage:

```
python send_command.py <LAN IP> <request> -p <relay port>
```

# Updating over the network
boot.py turns on WebREPL so you can update main.py without pulling the board back to a USB port.

1. Set the password in boot.py (`admin` by default, 4 to 9 characters).
2. Upload boot.py alongside main.py once, over USB. WebREPL now listens on port 8266 after boot.
3. Download [webrepl_cli.py](https://github.com/micropython/webrepl).
4. To push an update, run it from the directory holding your main.py, using your board's address:

```
python webrepl_cli.py -p <boot.py password> main.py <LAN IP>:/main.py
```

5. Apply the update by restarting the board with send_command.py, which sends a `reboot_board` command by default:

```
python send_command.py <LAN IP>
```

Run the push command from that directory rather than passing a full path, since `C:\...` reads as a second remote target. Keep WebREPL on the LAN and don't forward port 8266, it's plaintext with a weak password scheme.

# Raspberry Pi Pico W
Uses WiFi, so nothing but power has to reach the board.

Board specific parts:
- [Raspberry Pi Pico WH](https://www.raspberrypi.com/products/raspberry-pi-pico/) (soldered header) or solder jumper wires to a standard Pico W

Setup notes:
- Flash the [Pico W build of MicroPython](https://micropython.org/download/RPI_PICO_W/), or follow [Raspberry Pi's walkthrough](https://projects.raspberrypi.org/en/projects/get-started-pico-w/1).
- Set `WIRELESS_MODE` to `True` and fill in `__SSID` and `__PASSWORD`.
- Relays use GPIO2 (pin 4), GPIO3 (pin 5), and GPIO4 (pin 6). Power the relay from 3V3(OUT) (pin 36) and a GND pin (e.g. pin 38). [See pinout here](https://datasheets.raspberrypi.com/picow/PicoW-A4-Pinout.pdf).

# W5500-EVB-Pico
Same RP2040 as the Pico W with an onboard W5500 Ethernet controller instead of WiFi, so it shares a folder and a main.py with the Pico W. Worth it if the PC sits somewhere with bad WiFi.

Board specific parts:
- [W5500-EVB-Pico](https://docs.wiznet.io/Product/Chip/Ethernet/W5500/w5500-evb-pico) and an Ethernet cable

Setup notes:
- Flash the [W5500-EVB-Pico build of MicroPython](https://micropython.org/download/W5500_EVB_PICO/). The stock Pico build has no `network.WIZNET5K` and will fail on startup.
- Set `WIRELESS_MODE` to `False`. The SSID and password are ignored.
- The Ethernet controller is onboard and already wired to SPI0, so nothing extra is needed for it.
- Relays use the same GPIO2, GPIO3, and GPIO4 as the Pico W, and the same 3V3(OUT) and GND pins. The header matches the Pico's, but GPIO16 through GPIO21 are taken by the W5500 and can't be reused ([see pinout here](https://docs.wiznet.io/Product/Chip/Ethernet/W5500/w5500-evb-pico)).

# Olimex ESP32-POE
Ethernet plus Power over Ethernet, so one cable carries both network and power and the board needs no wall adapter. Requires a PoE capable switch or injector.

Board specific parts:
- [Olimex ESP32-POE](https://www.olimex.com/Products/IoT/ESP32/ESP32-POE/open-source-hardware) and an Ethernet cable
- A PoE switch or injector, or a USB-C cable if you'd rather power it that way

Setup notes:
- Flash the [generic ESP32 build of MicroPython](https://micropython.org/download/ESP32_GENERIC/) with [esptool](https://docs.espressif.com/projects/esptool/en/latest/esp32/), `esptool erase-flash` then `esptool write-flash 0x1000 ESP32_GENERIC-<version>.bin`. Auto reset works, so no need to hold the button.
- Relays use GPIO32, GPIO33, and GPIO4, all broken out on the two 10 pin headers and clear of the Ethernet block. Power the relay from the +3.3V and GND pins on the same headers ([see pinout here](https://github.com/OLIMEX/ESP32-POE/blob/master/DOCUMENTS/ESP32-POE-PINOUT.png)).
- Most of the ESP32's other GPIOs are used by the Ethernet PHY (12, 17, 18, 19, 21, 22, 23, 25, 26, 27) and aren't free. GPIO34 through GPIO39 are input only, and GPIO34 is the user button.
- `ENABLE_BLINKING` does nothing unless you wire your own LED to GPIO13. The 4 onboard LEDs are tied to the power rail and the Ethernet PHY, not to the ESP32, so no code can drive them.
- There is no SSID or password to set, the board takes DHCP as soon as the link comes up.
