import time

class Tagger:
    """
    Interface for the real Time Tagger device.
    Placeholders for actual driver calls.
    """
    def __init__(self, index=0, initialization_params: dict = {}):
        self.index = index
        print(f"[HW] Tagger initialized (Index: {index})")
        # TODO: Initialize real hardware
        # self.tagger = TimeTagger.createTag...

    def start_reading(self):
        print("[HW] Tagger started reading.")
        # TODO: self.tagger.start...

    def stop(self):
        print("[HW] Tagger stopped.")
        # TODO: self.tagger.stop...

    def get_data(self, timeout=5, return_splitted=False):
        """
        Returns data in the exact format of the real Tagger wrapper:
        List of [packet_num, events, channel, relative_time, absolute_time]
        """
        # TODO: Fetch real data
        # data = self.tagger.getData()
        # Process data...

        # Return empty list for now so the loop doesn't crash if we switch to this mode
        # accidentally without hardware.
        if return_splitted:
            return [], [], []
        return []

    # Configuration methods matching the Mock interface
    def set_trigger_level(self, level):
        print(f"[HW] Tagger set trigger level: {level}")

    def set_trigger_rising(self):
        print("[HW] Tagger set trigger rising")

    def set_trigger_falling(self):
        print("[HW] Tagger set trigger falling")

    def set_trigger_type(self, type='falling'):
        print(f"[HW] Tagger set trigger type: {type}")

    def enable_channel(self, channel):
        print(f"[HW] Tagger enable channel: {channel}")

    def disable_channel(self, channel):
        print(f"[HW] Tagger disable channel: {channel}")

    def set_channel_level(self, channel, level):
        print(f"[HW] Tagger set channel {channel} level: {level}")

    def set_channel_rising(self, channel):
        print(f"[HW] Tagger set channel {channel} rising")

    def set_channel_falling(self, channel):
        print(f"[HW] Tagger set channel {channel} falling")

    def set_type(self, channel, type='falling'):
        print(f"[HW] Tagger set channel {channel} type: {type}")

    def set_channel_window(self, channel, start=0, stop=600000):
        print(f"[HW] Tagger set channel {channel} window: {start}-{stop}")

    def init_card(self):
        print("[HW] Tagger init card")
