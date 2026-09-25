import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from control import parse_counter, parse_segment_colors, process_rgb_or_error
from bulbs.zengge_23byte import Zengge23Byte


class ChunkedSocket:
    def __init__(self, data, chunk_size):
        self.data = data
        self.chunk_size = chunk_size
        self.sent = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def settimeout(self, timeout):
        self.timeout = timeout

    def connect(self, address):
        self.address = address

    def sendall(self, data):
        self.sent.append(data)

    def recv(self, size):
        if not self.data:
            return b""
        count = min(size, self.chunk_size, len(self.data))
        chunk, self.data = self.data[:count], self.data[count:]
        return chunk


class Zengge23ByteProtocolTests(unittest.TestCase):
    def test_static_red_matches_captured_frame(self):
        bulb = Zengge23Byte("127.0.0.1", counter=0x1D)

        actual = bytes(
            bulb.add_checksum(bulb.process_rgb("255,0,0", brightness=27))
        )
        expected = bytes.fromhex(
            "B0 B1 B2 B3 00 01 02 1D 00 57 E1 03 00 14 00 00 14"
        ) + bytes.fromhex("A1 00 64 1B") * 20 + bytes.fromhex("C9")

        self.assertEqual(actual, expected)

    def test_rgb_without_brightness_uses_rgb_value_in_framed_command(self):
        bulb = Zengge23Byte("127.0.0.1", counter=0x1D)

        actual = bytes(bulb.add_checksum(bulb.process_rgb("255,0,0")))
        expected_body = bytes.fromhex(
            "B0 B1 B2 B3 00 01 02 1D 00 57 E1 03 00 14 00 00 14"
        ) + bytes.fromhex("A1 00 64 64") * 20

        self.assertEqual(actual[:-1], expected_body)
        self.assertEqual(actual[-1], sum(expected_body) & 0xFF)

    def test_static_blue_matches_captured_frame(self):
        bulb = Zengge23Byte("127.0.0.1", counter=0x25)

        actual = bytes(
            bulb.add_checksum(bulb.process_rgb("0,0,255", brightness=27))
        )
        expected = bytes.fromhex(
            "B0 B1 B2 B3 00 01 02 25 00 57 E1 03 00 14 00 00 14"
        ) + bytes.fromhex("A1 78 64 1B") * 20 + bytes.fromhex("31")

        self.assertEqual(actual, expected)

    def test_legacy_power_commands_remain_unchanged(self):
        bulb = Zengge23Byte("127.0.0.1")

        self.assertEqual(
            bytes(bulb.add_checksum(bulb.process_power("on"))),
            bytes.fromhex("71 23 0F A3"),
        )
        self.assertEqual(
            bytes(bulb.add_checksum(bulb.process_power("off"))),
            bytes.fromhex("71 24 0F A4"),
        )

    def test_segment_update_matches_captured_frame(self):
        colors = [(255, 0, 0)] * 14 + [(0, 0, 0)] * 6
        colors[1] = (0, 255, 0)
        bulb = Zengge23Byte("127.0.0.1", counter=0x46)

        actual = bytes(
            bulb.add_checksum(bulb.process_segments(colors, brightness=27))
        )
        expected = bytes.fromhex(
            "B0 B1 B2 B3 00 01 02 46 00 57 E1 03 00 14 00 00 14"
        )
        expected += bytes.fromhex("A1 00 64 1B")
        expected += bytes.fromhex("A1 3C 64 1B")
        expected += bytes.fromhex("A1 00 64 1B") * 12
        expected += bytes.fromhex("A1 00 00 00") * 6
        expected += bytes.fromhex("34")

        self.assertEqual(actual, expected)

    def test_segment_update_requires_exactly_twenty_slots(self):
        bulb = Zengge23Byte("127.0.0.1")

        with self.assertRaisesRegex(ValueError, "exactly 20"):
            bulb.process_segments([(255, 0, 0)] * 19)

    def test_observed_christmas_effect_frame_is_replayable_as_raw(self):
        bulb = Zengge23Byte("127.0.0.1")
        raw = (
            "B0:B1:B2:B3:00:01:02:51:00:23:E1:01:00:64:03:00:01:64:50:00:"
            "A1:00:00:00:05:A1:00:64:64:A1:19:E4:64:A1:3B:E4:64:"
            "A1:66:E4:64:A1:85:64:64"
        )

        actual = bytes(bulb.add_checksum(bulb.process_raw(raw)))
        expected = bytes.fromhex(
            "B0 B1 B2 B3 00 01 02 51 00 23 E1 01 00 64 03 00 01 64 50 00 "
            "A1 00 00 00 05 A1 00 64 64 A1 19 E4 64 A1 3B E4 64 "
            "A1 66 E4 64 A1 85 64 64 AD"
        )

        self.assertEqual(actual, expected)

    def test_white_mode_is_not_claimed_without_a_capture(self):
        bulb = Zengge23Byte("127.0.0.1")

        with self.assertRaisesRegex(NotImplementedError, "white-mode capture"):
            bulb.process_white([100, 255])

    def test_cli_segment_argument_parses_twenty_rgb_triples(self):
        raw = ";".join(["255,0,0"] * 20)

        self.assertEqual(parse_segment_colors(raw), [(255, 0, 0)] * 20)

    def test_cli_segment_argument_rejects_wrong_count(self):
        raw = ";".join(["255,0,0"] * 19)

        with self.assertRaisesRegex(ValueError, "exactly 20"):
            parse_segment_colors(raw)

    def test_counter_parser_accepts_hex_and_decimal_bytes(self):
        self.assertEqual(parse_counter("0x1d"), 0x1D)
        self.assertEqual(parse_counter("29"), 29)

    def test_counter_parser_rejects_values_outside_byte_range(self):
        with self.assertRaisesRegex(ValueError, "0 to 255"):
            parse_counter("256")

    def test_invalid_cli_rgb_is_reported_as_argument_error(self):
        class ParserStub:
            def error(self, message):
                raise RuntimeError(message)

        with self.assertRaisesRegex(RuntimeError, "between 0 and 255"):
            process_rgb_or_error(
                ParserStub(), Zengge23Byte("127.0.0.1"), "256,0,0", None
            )

    def test_status_query_uses_reported_legacy_request_bytes(self):
        self.assertEqual(
            Zengge23Byte.LEGACY_STATUS_REQUEST,
            bytes.fromhex("81 8A 8B 96"),
        )

    def test_get_status_sends_reported_unframed_request(self):
        response = bytes.fromhex(
            "EA 81 02 00 AA 09 23 25 FF 64 F0 B4 64 64 00 00 01 "
            "00 0E 00 00 00 20 01 00 00 01"
        )
        connection = ChunkedSocket(response, 4)

        with patch("bulbs.zengge_23byte.socket.socket", return_value=connection):
            with redirect_stdout(io.StringIO()):
                Zengge23Byte("127.0.0.1").get_status()

        self.assertEqual(connection.sent, [bytes.fromhex("81 8A 8B 96")])

    def test_status_response_reader_handles_fragmented_legacy_reply(self):
        response = bytes.fromhex(
            "EA 81 02 00 AA 09 23 25 FF 64 F0 B4 64 64 00 00 01 "
            "00 0E 00 00 00 20 01 00 00 01"
        )

        actual = Zengge23Byte.read_status_response(ChunkedSocket(response, 3))

        self.assertEqual(actual, response)

    def test_status_response_reader_handles_fragmented_framed_reply(self):
        response = bytes.fromhex(
            "B0 B1 B2 B3 00 01 02 1B 00 1B EA 81 01 00 AA 09 23 24 "
            "01 50 F0 B4 64 1B 00 00 01 00 0E 00 00 00 20 01 00 00 01 FF"
        )

        actual = Zengge23Byte.read_status_response(ChunkedSocket(response, 5))

        self.assertEqual(actual, response)

    def test_framed_status_response_returns_opaque_status_payload(self):
        response = bytes.fromhex(
            "B0 B1 B2 B3 00 01 02 1B 00 1B EA 81 01 00 AA 09 23 24 "
            "01 50 F0 B4 64 1B 00 00 01 00 0E 00 00 00 20 01 00 00 01 FF"
        )

        parsed = Zengge23Byte.parse_status_response(response)

        self.assertEqual(
            parsed,
            {
                "status_raw": (
                    "ea810100aa0923240150f0b4641b000001000e0000002001000001"
                )
            },
        )

    def test_unframed_status_response_preserves_all_bytes(self):
        response = bytes.fromhex(
            "EA 81 02 00 AA 09 23 25 FF 64 F0 B4 64 64 00 00 01 "
            "00 0E 00 00 00 20 01 00 00 01"
        )

        parsed = Zengge23Byte.parse_status_response(response)

        self.assertEqual(parsed["status_raw"], response.hex())


if __name__ == "__main__":
    unittest.main()
