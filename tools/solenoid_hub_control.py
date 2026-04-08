"""
solenoid_hub_control.py — USB hub port control via Adafruit 8-channel solenoid driver.

Hardware:
  - Adafruit I2C to 8 Channel Solenoid Driver (product #6318)
  - MCP23017 GPIO expander at I2C address 0x20
  - Solenoid channels 0-7 = MCP23017 port A pins A0-A7
  - Each channel drives a soft-latching button on the USB hub port
  - Pi Zero 2W at 192.168.1.234, I2C on bus 1

Timing sequences (soft-latching toggle buttons):
  ON:  200ms HIGH → 500ms LOW → 200ms HIGH → LOW
  OFF: 200ms HIGH → 500ms LOW → 1000ms HIGH → LOW

Usage:
    from solenoid_hub_control import SolenoidHubController
    hub = SolenoidHubController()
    hub.port_on(1)   # turn on USB hub port 1 (channel 1)
    hub.port_off(1)  # turn off USB hub port 1
    hub.cleanup()
"""

import time
import board
import busio
import digitalio
from adafruit_mcp230xx.mcp23017 import MCP23017


class SolenoidHubController:
    """
    Controls USB hub ports 0-6 via Adafruit 8-channel solenoid driver.
    Each channel maps to one USB hub port's soft-latching power button.
    """

    def __init__(self, i2c_address: int = 0x20):
        self.i2c = busio.I2C(board.SCL, board.SDA)
        self.mcp = MCP23017(self.i2c, address=i2c_address)
        self._pins = {}

    def _get_pin(self, channel: int):
        if channel not in self._pins:
            pin = self.mcp.get_pin(channel)
            pin.direction = digitalio.Direction.OUTPUT
            pin.value = False
            self._pins[channel] = pin
        return self._pins[channel]

    def port_on(self, channel: int) -> None:
        """
        Power ON sequence for USB hub port.
        Timing: 200ms HIGH → 500ms LOW → 200ms HIGH → LOW
        Ensures the soft-latching button registers as an ON press.
        """
        pin = self._get_pin(channel)
        pin.value = True;  time.sleep(0.200)
        pin.value = False; time.sleep(0.500)
        pin.value = True;  time.sleep(0.200)
        pin.value = False

    def port_off(self, channel: int) -> None:
        """
        Power OFF sequence for USB hub port.
        Timing: 200ms HIGH → 500ms LOW → 1000ms HIGH → LOW
        The longer final pulse distinguishes OFF from ON for the hub logic.
        """
        pin = self._get_pin(channel)
        pin.value = True;  time.sleep(0.200)
        pin.value = False; time.sleep(0.500)
        pin.value = True;  time.sleep(1.000)
        pin.value = False

    def all_off(self) -> None:
        """Send OFF sequence to all 7 hub ports (channels 0-6)."""
        for ch in range(7):
            self.port_off(ch)
            time.sleep(0.3)

    def cleanup(self) -> None:
        """Ensure all channels are LOW before releasing."""
        for pin in self._pins.values():
            pin.value = False
