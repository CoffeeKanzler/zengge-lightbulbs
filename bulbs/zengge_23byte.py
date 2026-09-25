import colorsys
import json
import socket

from .zengge import Zengge

class Zengge23Byte(Zengge):
    """Encoder for the captured AK001-ZJ21411 framed RGBIC protocol."""

    FRAME_HEADER = bytes.fromhex("B0 B1 B2 B3 00 01 02")
    SEGMENT_COUNT = 20
    RGB_SEGMENT_HEADER = bytes.fromhex("E1 03 00 14 00 00 14")
    LEGACY_STATUS_REQUEST = bytes.fromhex("81 8A 8B 96")
    LEGACY_STATUS_RESPONSE_LENGTH = 27

    def __init__(self, ip, counter=0):
        super().__init__(ip)
        if not 0 <= counter <= 0xFF:
            raise ValueError("counter must be between 0 and 255")
        self.counter = counter

    def _wrap_payload(self, payload):
        """Add the observed header, sequence counter, and big-endian length."""
        if len(payload) > 0xFFFF:
            raise ValueError("payload is too large for the controller frame")
        frame = (
            self.FRAME_HEADER
            + bytes((self.counter,))
            + len(payload).to_bytes(2, "big")
            + payload
        )
        self.counter = (self.counter + 1) & 0xFF
        return list(frame)

    @staticmethod
    def _rgb_to_hsv_bytes(rgb, brightness=None):
        if isinstance(rgb, str):
            components = rgb.split(",")
        else:
            components = list(rgb)
        if len(components) != 3:
            raise ValueError("RGB color must contain exactly three values")
        red, green, blue = map(int, components)
        if any(component < 0 or component > 255 for component in (red, green, blue)):
            raise ValueError("RGB values must be between 0 and 255")

        hue, saturation, value = colorsys.rgb_to_hsv(
            red / 255.0, green / 255.0, blue / 255.0
        )
        half_hue = int((hue * 360) / 2)
        saturation_percent = int(saturation * 100)
        value_percent = int(value * 100)
        if brightness is not None:
            brightness = int(brightness)
            if brightness < 0 or brightness > 100:
                raise ValueError("brightness must be between 0 and 100")
            if value_percent:
                value_percent = brightness
        return bytes((half_hue, saturation_percent, value_percent))

    def process_segments(self, rgb_values, brightness=None):
        """Build a full 20-slot segment update from RGB triples or strings."""
        if len(rgb_values) != self.SEGMENT_COUNT:
            raise ValueError(f"exactly {self.SEGMENT_COUNT} segment colors are required")
        records = b"".join(
            b"\xA1" + self._rgb_to_hsv_bytes(rgb, brightness)
            for rgb in rgb_values
        )
        payload = self.RGB_SEGMENT_HEADER + records
        return self._wrap_payload(payload)

    def process_rgb(self, rgb, brightness=None):
        """Set all 20 color slots to one RGB color."""
        return self.process_segments([rgb] * self.SEGMENT_COUNT, brightness)

    @classmethod
    def parse_status_response(cls, response):
        """Preserve status bytes until their individual fields are understood."""
        response = bytes(response)
        if response.startswith(cls.FRAME_HEADER):
            if len(response) < 11:
                raise ValueError("truncated AK001-ZJ21411 response frame")
            payload_length = int.from_bytes(response[8:10], "big")
            if len(response) != 11 + payload_length:
                raise ValueError("AK001-ZJ21411 response length does not match frame")
            # Captured response trailers do not match the observed request checksum,
            # so retain framing validation but do not invent a response checksum rule.
            response = response[10 : 10 + payload_length]
        return {"status_raw": response.hex()}

    @staticmethod
    def _recv_exact(connection, length):
        chunks = []
        remaining = length
        while remaining:
            chunk = connection.recv(remaining)
            if not chunk:
                raise ValueError("truncated AK001-ZJ21411 status response")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    @classmethod
    def read_status_response(cls, connection):
        """Read either the observed 27-byte legacy reply or a framed reply."""
        prefix = cls._recv_exact(connection, 2)
        if prefix == cls.FRAME_HEADER[:2]:
            header = prefix + cls._recv_exact(connection, 8)
            if header[:7] != cls.FRAME_HEADER:
                raise ValueError("invalid AK001-ZJ21411 response header")
            payload_length = int.from_bytes(header[8:10], "big")
            return header + cls._recv_exact(connection, payload_length + 1)
        return prefix + cls._recv_exact(
            connection, cls.LEGACY_STATUS_RESPONSE_LENGTH - len(prefix)
        )

    def get_status(self):
        """Send the issue-reported raw query and preserve its unknown reply."""
        try:
            with socket.socket() as connection:
                connection.settimeout(3)
                connection.connect((self.ip, 5577))
                connection.sendall(self.LEGACY_STATUS_REQUEST)
                response = self.read_status_response(connection)
            status = self.parse_status_response(response)
            print(json.dumps(status))
            return [f"{byte:02x}" for byte in response]
        except (OSError, ValueError):
            self.print_error("Could not get the bulb's status")

    def process_white(self, white):
        raise NotImplementedError(
            "white-mode capture is required before AK001-ZJ21411 support can be claimed"
        )
