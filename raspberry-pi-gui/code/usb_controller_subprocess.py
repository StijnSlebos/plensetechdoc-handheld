#!/usr/bin/env python3
"""
usb_controller_subprocess.py

Turn a specific port on/off on a UUGear MEGA4 hub by invoking the uhubctl binary.
"""

import logging
import subprocess
import time
from datetime import datetime


class USBControllerError(Exception):
    """Raised when uhubctl fails to run or returns an error."""
    pass


class USBController:
    """Controls per-port power on a UUGear MEGA4 hub via subprocess calls to uhubctl."""

    def __init__(self, hub_location: str, port: int):
        """
        :param hub_location: USB hub location string (e.g., '1-1.2')
        :param port: Port number to control (e.g., 1)
        """
        self.hub_location = hub_location
        self.port = port
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    def _run_uhubctl(self, action: int):
        """
        Invoke the uhubctl binary.
        :param action: 0 to turn off, 1 to turn on
        :raises USBControllerError: if the command fails
        """
        cmd = [
            "sudo", "uhubctl",
            "-l", self.hub_location,
            "-p", str(self.port),
            "-a", str(action),
        ]
        logging.info(f"Running: {' '.join(cmd)}")
        try:
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=10
            )
            logging.info(f"uhubctl output: {result.stdout.strip()}")
        except subprocess.CalledProcessError as e:
            msg = f"uhubctl exited {e.returncode}: {e.stderr.strip()}"
            logging.error(msg)
            raise USBControllerError(msg)
        except Exception as e:
            msg = f"Error running uhubctl: {e}"
            logging.error(msg)
            raise USBControllerError(msg)

    def power_cycle(self, off_duration: float = 5.0):
        """
        Turn off the port, wait, then turn it back on.
        :param off_duration: Seconds to keep the port off
        """
        logging.info(f"Powering OFF port {self.port}")
        self._run_uhubctl(action=0)

        logging.info(f"Sleeping for {off_duration} seconds")
        time.sleep(off_duration)

        logging.info(f"Powering ON port {self.port}")
        self._run_uhubctl(action=1)


if __name__ == "__main__":
    # CONFIGURE THESE
    HUB_LOCATION = "1-1.2"   # e.g. from `sudo uhubctl` scan
    PORT_NUMBER  = 1         # the port you want to cycle
    OFF_TIME_SEC = 5.0       # how many seconds to leave it off

    controller = USBController(hub_location=HUB_LOCATION, port=PORT_NUMBER)
    try:
        controller.power_cycle(off_duration=OFF_TIME_SEC)
        logging.info("Power cycle completed successfully.")
    except USBControllerError as err:
        logging.error(f"Power cycle failed: {err}")
        exit(1)
