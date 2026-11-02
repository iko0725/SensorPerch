"""Soft E-stop with a button."""

import os
import sys
import time
import argparse
from contextlib import contextmanager
from threading import Lock
from typing import Tuple, Optional, Union, Dict, Any

import numpy as np
import numpy.typing as npt

# Suppress ALSA and JACK warnings by redirecting stderr at file descriptor level
# These warnings come from C libraries and bypass Python's redirect_stderr
@contextmanager
def suppress_stderr():
    """Context manager to suppress stderr output (for ALSA/JACK warnings)."""
    original_stderr_fd = sys.stderr.fileno()
    devnull_fd = os.open(os.devnull, os.O_WRONLY)
    try:
        # Save original stderr
        saved_stderr_fd = os.dup(original_stderr_fd)
        # Redirect stderr to /dev/null
        os.dup2(devnull_fd, original_stderr_fd)
        yield
    finally:
        # Restore original stderr
        os.dup2(saved_stderr_fd, original_stderr_fd)
        os.close(saved_stderr_fd)
        os.close(devnull_fd)

# Import pyaudio with stderr suppressed
with suppress_stderr():
    import pyaudio


class Button:
    """Physical button that connects over audio jack."""

    PYAUDIO_STREAM_TROUBLESHOOTING = (
        "The PyAudio stream not opening error is often caused by another process using "
        "the microphone and/or audio device. To address this, terminate the code and "
        "try the following:\n"
        "  1. Close all applications (e.g., System Settings) that may be accessing "
        "audio devices.\n"
        "  2. If that still doesn't address it, run `sudo alsa force-reload`.\n"
        "     Wait a few (~5) secs after running this command to restart the node,\n"
        "     and note that you may have to run this command multiple times.\n"
        "Note that until this is addressed, the e-stop button will not be working."
    )

    def __init__(self, input_device_index: int, debug: bool = False, monitor: bool = False) -> None:
        self.start_time = time.time()
        self.prev_data_arr: Optional[npt.NDArray] = None
        self.detection_time: Optional[float] = None
        self.max_threshold: Union[int, float] = 10000
        self.min_threshold: Union[int, float] = -10000
        self.debug = debug
        self.monitor = monitor
        self.last_print_time = time.time()

        # Suppress ALSA/JACK warnings during PyAudio initialization
        with suppress_stderr():
            self.audio = pyaudio.PyAudio()

        try:
            # Suppress warnings during stream opening as well
            with suppress_stderr():
                self.stream = self.audio.open(
                    format=pyaudio.paInt16,
                    channels=1,  # The e-stop button is mono
                    rate=48000,
                    input=True,
                    frames_per_buffer=4800,
                    input_device_index=input_device_index,
                    stream_callback=self.__audio_callback,
                )
                # Start the stream - this is critical for the callback to be called!
                self.stream.start_stream()
        except OSError as exc:
            raise RuntimeError(
                (
                    f"Error opening audio device {input_device_index}. "
                    f"{Button.PYAUDIO_STREAM_TROUBLESHOOTING}\n\n"
                    f"Exception: {exc}"
                )
            )

        self.button_lock = Lock()
        self.button_value = False
        self.callback_count = 0  # Debug: track if callback is being called
        self.max_seen = 0  # Debug: track maximum signal value seen
        self.min_seen = 0  # Debug: track minimum signal value seen

    def close(self) -> None:
        """Close the audio stream."""
        if getattr(self, "stream", None) is not None:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception:
                pass
        self.audio.terminate()

    def check(self) -> bool:
        """Check if the e-stop button has been pressed."""
        with self.button_lock:
            return self.button_value

    def reset(self) -> None:
        """Reset the e-stop button."""
        with self.button_lock:
            self.button_value = False
    
    def get_signal_stats(self) -> Dict[str, Any]:
        """Get current signal statistics for monitoring."""
        return {
            'callback_count': self.callback_count,
            'max_seen': self.max_seen,
            'min_seen': self.min_seen,
            'max_threshold': self.max_threshold,
            'min_threshold': self.min_threshold,
            'is_active': self.stream.is_active() if hasattr(self, 'stream') else False,
        }

    def __audio_callback(
        self,
        data: bytes,
        frame_count: int,
        time_info: Dict[str, Any],
        status: int,
    ) -> Tuple[bytes, int]:
        del frame_count, time_info, status  # unused

        self.callback_count += 1
        data_arr = np.frombuffer(data, dtype=np.int16)
        
        # Track signal levels for debugging
        if data_arr.size > 0:
            curr_max = int(np.max(data_arr))
            curr_min = int(np.min(data_arr))
            curr_mean = float(np.mean(data_arr))
            curr_std = float(np.std(data_arr))
            if curr_max > self.max_seen:
                self.max_seen = curr_max
            if curr_min < self.min_seen:
                self.min_seen = curr_min

        # Monitor mode: print signal values periodically
        current_time = time.time()
        if self.monitor and (current_time - self.last_print_time) >= 0.5:  # Print every 0.5 seconds
            sample_values = data_arr[:10].tolist() if data_arr.size >= 10 else data_arr.tolist()
            # print(f"[Signal] max={curr_max:6d}, min={curr_min:6d}, mean={curr_mean:8.1f}, std={curr_std:8.1f}, "
            #       f"samples={sample_values}, callbacks={self.callback_count}")
            print(f"Button value: {self.button_value}, {curr_max - curr_min}")
            self.last_print_time = current_time

        # Skip the first few seconds of data, to avoid initial noise
        if time.time() - self.start_time < 2:
            if (self.debug or self.monitor) and self.callback_count % 100 == 0:
                print(f"Warming up... (callback {self.callback_count}, max: {self.max_seen}, min: {self.min_seen})")
            return (data, pyaudio.paContinue)

        # Check if the e-stop button has been pressed
        if Button.rising_edge_detector(
            data_arr,
            self.prev_data_arr,
            self.max_threshold,
        ) or Button.falling_edge_detector(
            data_arr,
            self.prev_data_arr,
            self.min_threshold,
        ):
            if self.detection_time is None or time.time() - self.detection_time > 2:
                self.detection_time = time.time()
                with self.button_lock:
                    self.button_value = True
                if self.debug or self.monitor:
                    print(f"\n*** Button detected! *** (max: {self.max_seen}, min: {self.min_seen}, threshold: ±{self.max_threshold})")

        # Debug output every 1000 callbacks
        if self.debug and self.callback_count % 1000 == 0:
            print(f"Callback {self.callback_count}: max signal={self.max_seen}, min signal={self.min_seen}, threshold=±{self.max_threshold}")

        # Return the data
        self.prev_data_arr = data_arr

        return (data, pyaudio.paContinue)

    @staticmethod
    def rising_edge_detector(
        curr_data_arr: npt.NDArray,
        prev_data_arr: Optional[npt.NDArray],
        threshold: Union[int, float],
    ) -> bool:
        """Detects whether there is a rising edge in `curr_data_arr` that
        exceeds `threshold`. In other words, this function returns True if
        there is a point in `curr_data_arr` that is greater than `threshold`
        and the previous point is less than `threshold`.

        Although this method of detecting a rising edge is susceptible to noise
        (since it only requires two points to determine an edge), in practice
        the e-stop button's signal has little noise. If noise is an issue
        moving forward, we can add a filter to smoothen the signal, and then
        continue using this detector.
        """
        is_above_threshold = curr_data_arr > threshold
        if np.any(is_above_threshold):
            first_index_above_threshold = int(np.argmax(is_above_threshold))
            # Get the previous value
            if first_index_above_threshold == 0:
                if prev_data_arr is None or prev_data_arr.size == 0:
                    # If the first datapoint is above the threshold, it's not a rising edge
                    return False
                prev_value = prev_data_arr[-1]
            else:
                prev_value = curr_data_arr[first_index_above_threshold - 1]
            # If the previous value is less than the threshold, it is a rising edge
            return bool(prev_value < threshold)
        # If no point is above the threshold, there is no rising edge
        return False

    @staticmethod
    def falling_edge_detector(
        curr_data_arr: npt.NDArray,
        prev_data_arr: Optional[npt.NDArray],
        threshold: Union[int, float],
    ) -> bool:
        """Detects whether there is a falling edge in `curr_data_arr` that
        exceeds `threshold`. In other words, this function returns True if
        there is a point in `curr_data_arr` that is less than `threshold` and
        the previous point is greater than `threshold`.
        """
        # Flip all signs and call the rising edge detector
        return Button.rising_edge_detector(
            -curr_data_arr,
            None if prev_data_arr is None else -prev_data_arr,
            -threshold,
        )


if __name__ == "__main__":
    # Redirect stderr to /dev/null to suppress ALSA/JACK warnings globally
    # These warnings come from C libraries and are harmless but clutter output
    original_stderr = sys.stderr
    devnull = open(os.devnull, 'w')
    sys.stderr = devnull
    original_stderr_fd = original_stderr.fileno()
    devnull_fd = devnull.fileno()
    saved_stderr_fd = os.dup(original_stderr_fd)
    os.dup2(devnull_fd, original_stderr_fd)
    
    try:
        # Set environment variables to suppress ALSA warnings
        os.environ['PYTHONWARNINGS'] = 'ignore'
        
        # add argument parser
        parser = argparse.ArgumentParser()
        parser.add_argument("--id", type=int, help="The index of the input device")
        parser.add_argument("--debug", action="store_true", help="Enable debug output to diagnose button detection")
        parser.add_argument("--monitor", action="store_true", help="Continuously print signal values to verify button is working")
        parser.add_argument("--threshold", type=int, default=10000, help="Detection threshold (default: 10000)")
        args = parser.parse_args()

        # -1 is user emergency stop button
        # 9 is experimenter emergency stop button
        # 7 is transfer button

        if args.id is None:
            # Suppress ALSA/JACK warnings when listing devices
            audio = pyaudio.PyAudio()
            device_indices = []
            for i in range(audio.get_device_count()):
                device_info = audio.get_device_info_by_index(i)
                if device_info.get("maxInputChannels", 0) > 0:  # Only consider input devices
                    device_indices.append(i)
                    print(f"Device {i}: {device_info.get('name', 'Unknown')}")
            audio.terminate()
            raise ValueError("Please provide the input device index, e.g., `--id 9`")

        button = Button(args.id, debug=args.debug, monitor=args.monitor)
        # Set custom threshold if provided
        if args.threshold != 100:
            button.max_threshold = args.threshold
            button.min_threshold = -args.threshold
            if args.debug or args.monitor:
                print(f"Using custom threshold: ±{args.threshold}")
        
        if args.debug or args.monitor:
            print(f"Button monitoring started. Waiting for button press...")
            print(f"Detection threshold: ±{button.max_threshold}")
            print("Press Ctrl+C to stop.")
            if args.monitor:
                print("Monitor mode: Signal values will be printed every 0.5 seconds")
                print("Watch the signal values - they should change when you press the button!\n")
        
        try:
            last_stats_time = time.time()
            while True:
                if button.check():
                    print("E-stop pressed!")
                    break
                
                # Print stats periodically in monitor mode (from main thread)
                if args.monitor and (time.time() - last_stats_time) >= 2.0:
                    stats = button.get_signal_stats()
                    # print(f"\n[Status] Callbacks: {stats['callback_count']}, "
                    #       f"Signal range: [{stats['min_seen']}, {stats['max_seen']}], "
                    #       f"Threshold: ±{stats['max_threshold']}, "
                    #       f"Stream active: {stats['is_active']}\n")
                    last_stats_time = time.time()
                
                time.sleep(0.01)
        finally:
            button.close()
    except (RuntimeError, ValueError) as e:
        # Restore stderr temporarily to show errors
        os.dup2(saved_stderr_fd, original_stderr_fd)
        sys.stderr = original_stderr
        raise
    finally:
        # Restore stderr
        os.dup2(saved_stderr_fd, original_stderr_fd)
        os.close(saved_stderr_fd)
        sys.stderr = original_stderr
        devnull.close()