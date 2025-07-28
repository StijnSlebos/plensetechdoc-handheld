#!/usr/bin/env python3
"""
Logger that redirects output to console and error.log file.
"""

import sys
import threading


class DualLogger:
    """
    Logger that writes messages to both the original stream and a log file.
    """
    def __init__(self, stream, log_file="error.log"):
        self.stream = stream
        # Open the log file in append mode with line buffering
        self.log_file = open(log_file, "a", buffering=1)

    def write(self, message):
        if threading.current_thread() is threading.main_thread():
            self.stream.write(message)
        self.log_file.write(message)

    def flush(self):
        if threading.current_thread() is threading.main_thread():
            self.stream.flush()
        self.log_file.flush()


sys.stdout = DualLogger(sys.stdout)
sys.stderr = DualLogger(sys.stderr) 