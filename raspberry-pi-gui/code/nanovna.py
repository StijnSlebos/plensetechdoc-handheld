#!/usr/bin/env python3
"""
NanoVNA continuous sweep script with auto-recovery via USB power-cycling.
"""
import logger_setup  # noqa: F401
import os
import time
import logging
import concurrent.futures
from datetime import datetime

import pynanovna
from usb_controller_subprocess import USBController, USBControllerError


class NanoVnaController:
    """Controls a NanoVNA with auto-recovery via USB port power-cycle."""

    def __init__(
        self,
        calibration_filename: str,
        sweep_range: tuple[float, float, int],
        hub_location: str,
        hub_port: int,
        output_dir: str = "output",
        log_file: str = "nanovna.log",
    ):
        # Resolve paths
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.calibration_file = os.path.join(base_dir, calibration_filename)
        self.output_dir = os.path.join(base_dir, output_dir)
        self.sweep_range = sweep_range

        # —— Logging Setup ——
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.INFO)
        fmt = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s",
            "%Y-%m-%d %H:%M:%S"
        )
        for handler in (
            logging.StreamHandler(),
            logging.FileHandler(log_file)
        ):
            handler.setFormatter(fmt)
            self.logger.addHandler(handler)

        # —— USB Controller for manual reboot ——
        self.usb_ctrl = USBController(hub_location=hub_location, port=hub_port)
        # self.usb_ctrl.power_cycle(off_duration=5.0)

        # —— Connect & configure VNA ——
        self._connect_vna(initial=True)
        start_hz, stop_hz, pts = sweep_range
        self.full_range = (start_hz, stop_hz)
        self.vna.set_sweep(start_hz, stop_hz, pts)
        self.logger.info(
            f"Sweep configured: {start_hz:.0f}->"
            f"{stop_hz:.0f} Hz, {pts} points"
        )
        self.logger.info(f"Calibration loaded: {self.calibration_file}")

        # —— Prepare output folder ——
        os.makedirs(self.output_dir, exist_ok=True)

    def _connect_vna(self, initial: bool = False):
        """(Re)connect to the NanoVNA and load calibration."""
        msg = "Initial connection to" if initial else "Reconnection to"
        self.logger.info(f"{msg} NanoVNA")
        try:
            self.vna = pynanovna.VNA(logging_level="info")
            if not self.vna.is_connected():
                self.logger.critical("NanoVNA not detected. Aborting.")
                raise ConnectionError("NanoVNA not connected")
            self.logger.info("NanoVNA connected.")
        except Exception as e:
            self.logger.critical(f"Failed to connect to NanoVNA: {e}")
            raise ConnectionError(f"Failed to connect to NanoVNA: {e}") from e

        # Load calibration
        try:
            self.vna.load_calibration(self.calibration_file)
            self.logger.info(f"Calibration loaded: {self.calibration_file}")
        except Exception:
            self.logger.exception("Failed to load calibration.")
            raise

    def _write_s2p(self, fname, freq, s11, s21):
        """Write Touchstone .s2p file."""
        with open(fname, "w") as f:
            f.write("# Hz S RI R 50\n")
            for hz, c11, c21 in zip(freq, s11, s21):
                f.write(
                    f"{int(hz)} "
                    f"{c11.real:.6e} {c11.imag:.6e} "
                    f"{c21.real:.6e} {c21.imag:.6e} "
                    f"{c21.real:.6e} {c21.imag:.6e} "
                    f"{c11.real:.6e} {c11.imag:.6e}\n"
                )

    def _reinitialize_vna_with_timeout(self, max_retries=3, timeout=10):
        """Attempt reinitialization (with USB power-cycle) under a timeout."""
        for attempt in range(1, max_retries + 1):
            self.logger.info(f"Recovery attempt {attempt}/{max_retries}")
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=1
            ) as executor:
                future = executor.submit(self._reinitialize_vna_once)
                try:
                    if future.result(timeout=timeout):
                        return True
                except concurrent.futures.TimeoutError:
                    self.logger.error("Reinit timed out.")
            time.sleep(1)
        return False

    def _reinitialize_vna_once(self):
        """One attempt: kill, USB reboot port, reconnect."""
        try:
            self.vna.kill()
        except Exception:
            pass
        time.sleep(2)

        # USB reboot
        try:
            self.logger.warning("Power-cycling USB port to reboot VNA…")
            self.usb_ctrl.power_cycle(off_duration=5.0)
            self.logger.info("USB reboot complete.")
        except USBControllerError as e:
            self.logger.error(f"USB reboot error: {e}")

        time.sleep(2)
        try:
            self._connect_vna(initial=False)
            return True
        except Exception as e:
            self.logger.error(f"Reconnect failed: {e}")
            return False

    def sweep_and_save(
        self,
        segments: int = 16,
        points_per_segment: int = 256,
        timestamp: str = None
    ):
        """
        Segmented sweep with retries and recovery.
        Only saves if *all* segments complete successfully.
        Returns True if successful, False otherwise.
        """
        start_hz, stop_hz = self.full_range
        freqs_all, s11_all, s21_all = [], [], []
        bounds = [
            start_hz + i * (stop_hz - start_hz) / segments
            for i in range(segments + 1)
        ]

        full_success = True

        for i in range(segments):
            f0, f1 = bounds[i], bounds[i + 1]
            self.vna.set_sweep(f0, f1, points_per_segment)
            self.logger.info(
                f"Sweeping segment {i+1}/{segments}: {f0:.0f}->"
                f"{f1:.0f} Hz"
            )

            segment_done = False
            for retry in range(1, 4):
                try:
                    s11, s21, freq = self.vna.sweep()
                    freqs_all.extend(freq)
                    s11_all.extend(s11)
                    s21_all.extend(s21)
                    segment_done = True
                    break
                except Exception as e:
                    self.logger.warning(f"Segment {i+1} retry {retry}: {e}")
                    if retry < 3 and self._reinitialize_vna_with_timeout():
                        time.sleep(2 ** retry)
                        continue
                    break

            if not segment_done:
                self.logger.error(f"Segment {i+1} failed after retries.")
                full_success = False
                break

        if not full_success:
            self.logger.error("Full sweep failed—no file will be saved.")
            return False

        # Use provided timestamp or generate a new one
        if timestamp is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = os.path.join(
            self.output_dir,
            f"sweep_{timestamp}.s2p"
        )
        self._write_s2p(fname, freqs_all, s11_all, s21_all)
        self.logger.info(f"Sweep saved: {fname}")
        return True

    def _check_vna_state(self) -> bool:
        """Quick health check: connected + simple sweep."""
        try:
            if not self.vna.is_connected():
                self.logger.warning("VNA disconnected.")
                return False
            # try a zero-point sweep
            self.vna.set_sweep(*self.sweep_range)
            self.vna.sweep()
            return True
        except Exception:
            return False

    def run(self, interval_min: float = 5.0):
        """
        Main loop: continuous sweeps every `interval_min` minutes (supports
        fractions), with recovery.
        """
        self.logger.info(f"Starting sweeps every {interval_min} min")
        interval_sec = interval_min * 60.0
        failure_count = 0

        while True:
            start = time.time()
            try:
                if not self._check_vna_state():
                    self.logger.warning("VNA unhealthy; attempting recovery.")
                    if not self._reinitialize_vna_with_timeout():
                        self.logger.error("Recovery failed; waiting 30 s")
                        time.sleep(30)
                        continue

                self.sweep_and_save()
                failure_count = 0

                elapsed = time.time() - start
                wait = max(0, interval_sec - elapsed)
                self.logger.info(f"Next sweep in {wait:.1f} s")
                time.sleep(wait)

            except KeyboardInterrupt:
                self.logger.info("Interrupted by user; shutting down.")
                break

            except Exception as e:
                failure_count += 1
                self.logger.error(f"Loop error: {e}")
                if failure_count >= 5:
                    self.logger.warning("5 errors; full recovery.")
                    self._reinitialize_vna_with_timeout()
                    failure_count = 0   
                time.sleep(10)

        # final cleanup
        try:
            self.logger.info("Killing VNA connection.")
            self.vna.kill()
        except Exception:
            pass


if __name__ == "__main__":
    # CONFIGURATION
    CAL_FILE_NAME = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), 
        "calibration", 
        "calibration_10-500khz.cal"
    )
    SWEEP_RANGE = (10e3, 500e3, 256)  # 10 kHz → 500 kHz, 256 points
    HUB_LOCATION = "1-1.2"  # from `sudo uhubctl`
    HUB_PORT = 1  # Mega4 port where NanoVNA is plugged
    INTERVAL_MIN = 5  # minutes between sweeps (0.5 = 30 s)
    OUTPUT_FOLDER = "output"

    controller = NanoVnaController(
        calibration_filename=CAL_FILE_NAME,
        sweep_range=SWEEP_RANGE,
        hub_location=HUB_LOCATION,
        hub_port=HUB_PORT,
        output_dir=OUTPUT_FOLDER,
    )
    controller.run(interval_min=INTERVAL_MIN)
