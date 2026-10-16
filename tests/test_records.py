"""Fixture encoding. These bytes are what the program under test actually reads."""

import os
import unittest

from cobolkit import copybook, records
from cobolkit.records import EBCDIC

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")
CUSTREC = os.path.join(FIXTURES, "copybooks", "CUSTREC.cpy")


class TestPackedDecimal(unittest.TestCase):
    def test_odd_digit_count_packs_exactly(self):
        self.assertEqual(
            records.pack_decimal(123456789, 9, True), bytes.fromhex("123456789C")
        )

    def test_negative_sign_nibble_is_d(self):
        self.assertEqual(records.pack_decimal(-1, 3, True), bytes.fromhex("001D"))

    def test_unsigned_sign_nibble_is_f(self):
        self.assertEqual(records.pack_decimal(1, 3, False), bytes.fromhex("001F"))

    def test_even_digit_count_gets_a_leading_pad_nibble(self):
        packed = records.pack_decimal(12345678, 8, True)
        self.assertEqual(packed, bytes.fromhex("012345678C"))
        self.assertEqual(len(packed), 5)

    def test_value_is_zero_padded_to_the_declared_width(self):
        self.assertEqual(records.pack_decimal(7, 5, False), bytes.fromhex("00007F"))

    def test_unsigned_field_keeps_nibble_f_even_for_a_negative_value(self):
        # Matches COBOL: moving a negative into an unsigned field loses the sign.
        self.assertEqual(records.pack_decimal(-7, 3, False), bytes.fromhex("007F"))


class TestZonedDecimal(unittest.TestCase):
    def test_ebcdic_digits_use_the_f_zone(self):
        self.assertEqual(records.pack_zoned(123, 3, False, EBCDIC), bytes.fromhex("F1F2F3"))

    def test_negative_overpunches_the_last_digit(self):
        self.assertEqual(records.pack_zoned(-123, 3, True, EBCDIC), bytes.fromhex("F1F2D3"))

    def test_positive_signed_overpunches_with_c(self):
        self.assertEqual(records.pack_zoned(123, 3, True, EBCDIC), bytes.fromhex("F1F2C3"))

    def test_ascii_mode_emits_plain_digits(self):
        self.assertEqual(records.pack_zoned(-123, 3, True, "ascii"), b"123")


class TestBinary(unittest.TestCase):
    def test_big_endian(self):
        self.assertEqual(records.pack_binary(1, 2), b"\x00\x01")
        self.assertEqual(records.pack_binary(256, 2), b"\x01\x00")

    def test_twos_complement(self):
        self.assertEqual(records.pack_binary(-1, 2), b"\xff\xff")

    def test_overflow_is_an_error(self):
        with self.assertRaises(records.EncodingError):
            records.pack_binary(70000, 2)


class TestRecordBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.record = copybook.parse_file(CUSTREC)[0]

    def test_every_case_produces_a_full_length_record(self):
        for case in records.CASES:
            with self.subTest(case=case):
                data = records.build(self.record, case)
                self.assertEqual(len(data), 172)

    def test_fill_cases_are_uniform(self):
        self.assertEqual(records.build(self.record, "low-values"), b"\x00" * 172)
        self.assertEqual(records.build(self.record, "high-values"), b"\xff" * 172)

    def test_unset_bytes_default_to_ebcdic_space(self):
        data = records.build(self.record, "zero")
        # The trailing FILLER is never populated, so it stays blank.
        self.assertEqual(data[162:172], b"\x40" * 10)

    def test_numeric_fields_land_at_their_offsets(self):
        data = records.build(self.record, "zero")
        self.assertEqual(data[0:8], bytes.fromhex("F0F0F0F0F0F0F0F0"))

    def test_max_case_fills_the_packed_balance(self):
        data = records.build(self.record, "max")
        # CUST-BALANCE: S9(9)V99 COMP-3 at position 60, 6 bytes, all nines.
        self.assertEqual(data[59:65], bytes.fromhex("99999999999C"))

    def test_min_case_makes_the_packed_balance_negative(self):
        data = records.build(self.record, "min")
        self.assertEqual(data[59:65], bytes.fromhex("99999999999D"))

    def test_binary_field_is_two_bytes_at_its_offset(self):
        data = records.build(self.record, "max")
        # CUST-REGION-CODE: PIC 9(4) COMP, unsigned, max 9999 == 0x270F.
        self.assertEqual(data[78:80], bytes.fromhex("270F"))

    def test_unknown_case_is_rejected(self):
        with self.assertRaises(records.EncodingError):
            records.build(self.record, "nonsense")

    def test_ascii_mode_is_readable(self):
        data = records.build(self.record, "typical", "ascii")
        self.assertEqual(len(data), 172)
        self.assertTrue(data[9:29].decode("ascii").startswith("CUSTFIRST"))


class TestBoundaries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.record = copybook.parse_file(CUSTREC)[0]
        cls.rows = {b.path.split(".")[-1]: b for b in records.boundaries(cls.record)}

    def test_one_row_per_elementary_field(self):
        elementary = self.record.flatten(elementary_only=True)
        self.assertEqual(len(records.boundaries(self.record)), len(elementary))

    def test_signed_packed_field_covers_both_bounds(self):
        row = self.rows["CUST-BALANCE"]
        self.assertIn("-99999999999", row.values)
        self.assertIn("99999999999", row.values)
        self.assertIn("0", row.values)

    def test_scale_is_called_out(self):
        row = self.rows["CUST-BALANCE"]
        self.assertTrue(any("decimal place" in n for n in row.notes), row.notes)

    def test_unsigned_field_warns_about_silent_sign_loss(self):
        row = self.rows["CUST-ID"]
        self.assertTrue(any("unsigned" in n for n in row.notes), row.notes)

    def test_binary_field_warns_about_its_physical_range(self):
        row = self.rows["CUST-REGION-CODE"]
        self.assertTrue(any("COMP occupies" in n for n in row.notes), row.notes)

    def test_text_field_warns_about_ebcdic_collation(self):
        row = self.rows["CUST-FIRST"]
        self.assertTrue(any("collation" in n for n in row.notes), row.notes)

    def test_occurs_depending_on_demands_boundary_occurrences(self):
        row = self.rows["CUST-PHONE-TYPE"]
        self.assertTrue(any("OCCURS 5" in n for n in row.notes), row.notes)


class TestHexdump(unittest.TestCase):
    def test_offsets_and_characters(self):
        dump = records.hexdump(bytes.fromhex("C1C2C3"), charset=EBCDIC)
        self.assertIn("000000", dump)
        self.assertIn("C1 C2 C3", dump)
        self.assertIn("|ABC|", dump)


if __name__ == "__main__":
    unittest.main()
