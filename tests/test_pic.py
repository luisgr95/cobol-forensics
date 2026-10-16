"""Storage sizing. Every case here is one a real copybook gets wrong."""

import unittest

from cobolkit.pic import (
    BINARY,
    DISPLAY,
    PACKED,
    PictureError,
    binary_size,
    parse_picture,
    storage_for,
    value_range,
)


def size(picture: str, usage: str = DISPLAY, sign_separate: bool = False) -> int:
    return storage_for(parse_picture(picture), usage, sign_separate).size


class TestDisplaySizing(unittest.TestCase):
    def test_digits_and_characters_cost_one_byte_each(self):
        self.assertEqual(size("9(8)"), 8)
        self.assertEqual(size("X(20)"), 20)
        self.assertEqual(size("A(5)"), 5)
        self.assertEqual(size("XXX"), 3)

    def test_sign_is_overpunched_and_costs_nothing(self):
        self.assertEqual(size("S9(5)"), 5)

    def test_sign_separate_costs_one_byte(self):
        self.assertEqual(size("S9(5)", DISPLAY, sign_separate=True), 6)

    def test_implied_decimal_point_costs_nothing(self):
        self.assertEqual(size("9(5)V99"), 7)
        self.assertEqual(parse_picture("9(5)V99").scale, 2)

    def test_scaling_positions_cost_nothing_but_count_as_digits(self):
        picture = parse_picture("9(3)PPP")
        self.assertEqual(storage_for(picture, DISPLAY).size, 3)
        self.assertEqual(picture.digits, 6)

    def test_editing_characters_occupy_bytes(self):
        # Z Z , Z Z 9 . 9 9 -- nine positions, three of them real digits.
        picture = parse_picture("ZZ,ZZ9.99")
        self.assertEqual(storage_for(picture, DISPLAY).size, 9)
        self.assertEqual(picture.digits, 3)
        self.assertEqual(picture.category, "numeric-edited")

    def test_floating_sign_occupies_a_byte(self):
        self.assertEqual(size("-9(9)"), 10)

    def test_national_is_two_bytes_per_position(self):
        self.assertEqual(size("N(10)"), 20)


class TestPackedDecimal(unittest.TestCase):
    def test_even_digit_count_packs_with_a_pad_nibble(self):
        # 8 digits + sign = 9 nibbles, rounded up to 5 bytes.
        self.assertEqual(size("S9(8)", PACKED), 5)

    def test_odd_digit_count_packs_exactly(self):
        # 9 digits + sign = 10 nibbles = 5 bytes, no waste.
        self.assertEqual(size("S9(9)", PACKED), 5)

    def test_implied_decimals_count_toward_the_digit_total(self):
        self.assertEqual(size("S9(9)V99", PACKED), 6)
        self.assertEqual(size("S9(7)V99", PACKED), 5)

    def test_single_digit(self):
        self.assertEqual(size("9", PACKED), 1)

    def test_unsigned_packed_is_the_same_size(self):
        self.assertEqual(size("9(9)", PACKED), size("S9(9)", PACKED))


class TestBinary(unittest.TestCase):
    def test_width_comes_from_digit_bands(self):
        self.assertEqual(binary_size(1), 2)
        self.assertEqual(binary_size(4), 2)
        self.assertEqual(binary_size(5), 4)
        self.assertEqual(binary_size(9), 4)
        self.assertEqual(binary_size(10), 8)
        self.assertEqual(binary_size(18), 8)

    def test_pictures_map_to_those_bands(self):
        self.assertEqual(size("9(4)", BINARY), 2)
        self.assertEqual(size("S9(9)", BINARY), 4)
        self.assertEqual(size("9(10)", BINARY), 8)

    def test_over_eighteen_digits_is_rejected(self):
        with self.assertRaises(PictureError):
            binary_size(19)

    def test_alignment_matches_width(self):
        self.assertEqual(storage_for(parse_picture("9(4)"), BINARY).alignment, 2)
        self.assertEqual(storage_for(parse_picture("S9(9)"), BINARY).alignment, 4)


class TestFloatAndPointer(unittest.TestCase):
    def test_fixed_width_usages_need_no_picture(self):
        self.assertEqual(storage_for(None, "COMP-1").size, 4)
        self.assertEqual(storage_for(None, "COMP-2").size, 8)
        self.assertEqual(storage_for(None, "INDEX").size, 4)
        self.assertEqual(storage_for(None, "POINTER").size, 4)

    def test_a_picture_is_required_otherwise(self):
        with self.assertRaises(PictureError):
            storage_for(None, DISPLAY)


class TestValueRange(unittest.TestCase):
    def test_unsigned_display_starts_at_zero(self):
        self.assertEqual(value_range(parse_picture("9(2)")), (0, 99))

    def test_signed_display_is_symmetric(self):
        self.assertEqual(value_range(parse_picture("S9(3)")), (-999, 999))

    def test_binary_is_capped_by_its_declared_precision(self):
        # PIC S9(4) COMP holds two bytes, so the hardware allows +-32767, but
        # the declared precision is what the program promises.
        self.assertEqual(value_range(parse_picture("S9(4)"), BINARY), (-9999, 9999))

    def test_binary_hardware_limit_applies_when_it_is_the_tighter_bound(self):
        low, high = value_range(parse_picture("S9(9)"), BINARY)
        self.assertEqual((low, high), (-999999999, 999999999))

    def test_non_numeric_is_rejected(self):
        with self.assertRaises(PictureError):
            value_range(parse_picture("X(4)"))


class TestMalformedPictures(unittest.TestCase):
    def test_empty_is_rejected(self):
        with self.assertRaises(PictureError):
            parse_picture("   ")

    def test_unknown_symbol_is_rejected(self):
        with self.assertRaises(PictureError):
            parse_picture("9(3)%")


if __name__ == "__main__":
    unittest.main()
