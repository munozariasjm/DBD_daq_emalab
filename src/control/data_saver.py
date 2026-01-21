import threading
import time
import queue
import csv
import os

class DataSaver(threading.Thread):
    def __init__(self, filename, flush_interval=1.0):
        super().__init__()
        self.filename = filename
        self.flush_interval = flush_interval
        self.queue = queue.Queue()
        self.stop_event = threading.Event()

        # Ensure directory exists
        os.makedirs(os.path.dirname(os.path.abspath(filename)), exist_ok=True)

        self.headers_written = os.path.exists(filename)

    def add_event(self, data: dict):
        """
        Add a dictionary of data to the save queue.
        Keys must remain consistent for CSV writing.
        """
        self.queue.put(data)

    def run(self):
        last_flush = time.time()
        buffer = []

        while not self.stop_event.is_set():
            try:
                # Poll frequently to check for stop event
                item = self.queue.get(timeout=0.1)
                buffer.append(item)
            except queue.Empty:
                pass

            now = time.time()
            if (now - last_flush >= self.flush_interval) or (len(buffer) >= 1000):
                if buffer:
                    self._flush_buffer(buffer)
                    buffer = []
                last_flush = now

        # Final flush on exit
        if buffer:
            self._flush_buffer(buffer)
        print(f"[Saver] Thread stopped. File: {self.filename}")

    def stop(self):
        self.stop_event.set()
        self.join()

    def _flush_buffer(self, buffer):
        if not buffer:
            return

        # grab keys from first item
        keys = buffer[0].keys()

        try:
            # Open in append mode
            with open(self.filename, 'a', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                if not self.headers_written:
                    writer.writeheader()
                    self.headers_written = True
                writer.writerows(buffer)
                f.flush()
            # print(f"[Saver] Wrote {len(buffer)} lines.")
        except Exception as e:
            print(f"[Saver] Error writing to disk: {e}")
