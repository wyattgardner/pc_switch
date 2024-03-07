# pc_switch
Raspberry Pi Pico W project to turn on a PC over the internet

Required Parts:

Raspberry Pi Pico WH or Pico W with soldered header

Jumper wire splitter ([what I used](https://www.amazon.com/gp/product/B0CNYJZ8D7/))

3.3V Relay ([what I used](https://www.amazon.com/gp/product/B08W3XDNGK/?th=1))

Various jumper wires

Setup:
1. Refer to [Raspberry Pi's documentation](https://projects.raspberrypi.org/en/projects/get-started-pico-w/1) for initial setup of Pico W
2. Upload main.py to root directory of Pico W ([method recommended by Raspberry Pi](https://projects.raspberrypi.org/en/projects/getting-started-with-the-pico/9), other methods include using BOOTSEL to copy it directly or using the MicroPico extension in VS Code)
3. Disconnect power button wires from power button pins on your PC's motherboard.
4. Connect a jumper wire splitter to the pins and reconnect the power button wires to one end of the splitter.
5. On the other end of the splitter, run two jumper wires to the NO and COM pins of the relay.
6. Use jumper wires to connect GPIO2 (pin 4) to relay's IN pin, 3V3(OUT) (pin 36) to relay's VCC pin, and a GND pin (e.g. pin 38) to relay's GND pin.
7. Power the board to start the program.
8. Figure out the LAN address assigned to the board. You could look at your network gateway's UI or view the program's output over a MicroPython REPL connection (e.g. MicroPico)
9. Enter the LAN address into the [accompanying Android app](https://github.com/wyattgardner/pc_switch_app).
9b. To use your network's WAN address to send the packet, you must forward the port you're using (7776 by default) to the Pico W.
10. You can now use the app to turn on your PC.
