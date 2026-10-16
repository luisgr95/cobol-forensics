"""Byte-map correctness. An error of one byte here corrupts every later field."""

import os
import textwrap
import unittest

from cobolkit import copybook

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")
CUSTREC = os.path.join(FIXTURES, "copybooks", "CUSTREC.cpy")


def fixed(text: str) -> str:
    """Indent a free-written snippet into fixed-format Area B."""
    return textwrap.indent(textwrap.dedent(text).strip("\n"), " " * 11)


class TestCustrecByteMap(unittest.TestCase):
    """Positions computed by hand from the IBM storage rules."""

    EXPECTED = {
        "CUSTOMER-RECORD": (1, 172),
        "CUST-ID": (1, 8),
        "CUST-STATUS": (9, 1),
        "CUST-NAME": (10, 50),
        "CUST-FIRST": (10, 20),
        "CUST-LAST": (30, 30),
        "CUST-NAME-FLAT": (10, 50),
        "CUST-BALANCE": (60, 6),
        "CUST-CREDIT-LIMIT": (66, 5),
        "CUST-OPEN-DATE": (71, 8),
        "CUST-REGION-CODE": (79, 2),
        "CUST-PHONE-COUNT": (81, 2),
        "CUST-PHONES": (83, 80),
        "CUST-PHONE-TYPE": (83, 1),
        "CUST-PHONE-NUMBER": (84, 15),
    }

    @classmethod
    def setUpClass(cls):
        cls.records = copybook.parse_file(CUSTREC)
        cls.record = cls.records[0]

    def test_one_record_named_after_the_01_level(self):
        self.assertEqual(len(self.records), 1)
        self.assertEqual(self.record.name, "CUSTOMER-RECORD")

    def test_record_length(self):
        self.assertEqual(self.record.length, 172)

    def test_every_field_lands_where_it_should(self):
        for name, (position, length) in self.EXPECTED.items():
            with self.subTest(field=name):
                node = self.record.find(name)
                self.assertIsNotNone(node, f"{name} not found")
                self.assertEqual(node.position, position, f"{name} position")
                self.assertEqual(node.total_size, length, f"{name} length")

    def test_redefines_shares_the_original_offset(self):
        group = self.record.find("CUST-NAME")
        flat = self.record.find("CUST-NAME-FLAT")
        self.assertEqual(flat.offset, group.offset)
        self.assertEqual(flat.redefines, "CUST-NAME")

    def test_redefines_does_not_consume_extra_storage(self):
        # 8 + 1 + 50 + 6 + 5 + 8 + 2 + 2 + 80 + 10 == 172, with the 50-byte
        # redefinition contributing nothing. Summed over the 05 level, because
        # OCCURS multiplication lives on the group, not on its children.
        top = [f for f in self.record.fields[0].children if not f.redefines]
        self.assertEqual(sum(f.total_size for f in top), 172)

    def test_filler_is_kept_because_it_occupies_bytes(self):
        fillers = [f for f in self.record.flatten() if f.name == "FILLER"]
        self.assertEqual(len(fillers), 1)
        self.assertEqual(fillers[0].position, 163)

    def test_occurs_multiplies_the_unit_size(self):
        phones = self.record.find("CUST-PHONES")
        self.assertEqual(phones.unit_size, 16)
        self.assertEqual(phones.occurs, 5)
        self.assertEqual(phones.total_size, 80)

    def test_depending_on_is_recorded_and_warned_about(self):
        phones = self.record.find("CUST-PHONES")
        self.assertEqual(phones.depending_on, "CUST-PHONE-COUNT")
        self.assertEqual(phones.occurs_min, 1)
        self.assertTrue(phones.variable)
        self.assertTrue(self.record.fields[0].variable)
        self.assertTrue(
            any("DEPENDING ON" in w for w in self.record.warnings),
            self.record.warnings,
        )

    def test_condition_names_attach_to_their_field(self):
        status = self.record.find("CUST-STATUS")
        names = [name for name, _ in status.conditions]
        self.assertEqual(
            names, ["CUST-ACTIVE", "CUST-CLOSED", "CUST-SUSPENDED", "CUST-BILLABLE"]
        )
        values = dict(status.conditions)
        self.assertEqual(values["CUST-ACTIVE"], "'A'")
        self.assertEqual(values["CUST-BILLABLE"], "'A' 'S'")

    def test_nested_condition_names_are_not_hoisted(self):
        phone_type = self.record.find("CUST-PHONE-TYPE")
        self.assertEqual(
            [n for n, _ in phone_type.conditions],
            ["PHONE-IS-MOBILE", "PHONE-IS-LANDLINE"],
        )

    def test_paths_are_qualified(self):
        self.assertEqual(
            self.record.find("CUST-FIRST").path, "CUSTOMER-RECORD.CUST-NAME.CUST-FIRST"
        )

    def test_group_items_carry_no_picture(self):
        self.assertTrue(self.record.find("CUST-NAME").is_group)
        self.assertIsNone(self.record.find("CUST-NAME").picture)


class TestSynchronized(unittest.TestCase):
    def test_sync_inserts_slack_bytes_before_a_binary_field(self):
        source = fixed(
            """
            01  SYNCREC.
                05  SR-FLAG                 PIC X.
                05  SR-COUNT                PIC S9(9) COMP SYNC.
            """
        )
        record = copybook.parse(source)[0]
        count = record.find("SR-COUNT")
        # One byte used, so the fullword field aligns at offset 4.
        self.assertEqual(count.slack_before, 3)
        self.assertEqual(count.position, 5)
        self.assertEqual(record.length, 8)

    def test_no_slack_when_already_aligned(self):
        source = fixed(
            """
            01  SYNCREC.
                05  SR-PAD                  PIC X(4).
                05  SR-COUNT                PIC S9(9) COMP SYNC.
            """
        )
        record = copybook.parse(source)[0]
        self.assertEqual(record.find("SR-COUNT").slack_before, 0)
        self.assertEqual(record.length, 8)

    def test_without_sync_there_is_no_alignment(self):
        source = fixed(
            """
            01  SYNCREC.
                05  SR-FLAG                 PIC X.
                05  SR-COUNT                PIC S9(9) COMP.
            """
        )
        record = copybook.parse(source)[0]
        self.assertEqual(record.find("SR-COUNT").position, 2)
        self.assertEqual(record.length, 5)


class TestParsingEdges(unittest.TestCase):
    def test_free_format_is_detected(self):
        source = (
            "01 THING.\n"
            "   05 THING-A PIC X(3).\n"
            "   05 THING-B PIC 9(4) COMP.\n"
        )
        record = copybook.parse(source)[0]
        self.assertEqual(record.length, 5)

    def test_text_past_column_72_is_not_code(self):
        # The trailing identification field must not be read as a clause.
        line = " " * 7 + "01  REC PIC X(4)." + " " * 40 + "IGNORED99"
        record = copybook.parse(line + "\n")[0]
        self.assertEqual(record.length, 4)

    def test_comment_lines_are_skipped(self):
        source = "      * 01 NOT-A-FIELD PIC X(99).\n" + fixed(
            """
            01  REAL-REC                    PIC X(4).
            """
        )
        records = copybook.parse(source)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].name, "REAL-REC")

    def test_level_77_is_a_standalone_record(self):
        record = copybook.parse(fixed("77  LONE-COUNT PIC S9(4) COMP.\n"))[0]
        self.assertEqual(record.name, "LONE-COUNT")
        self.assertEqual(record.length, 2)

    def test_level_66_renames_declares_no_storage(self):
        source = fixed(
            """
            01  REC.
                05  REC-A                   PIC X(2).
                05  REC-B                   PIC X(3).
            66  REC-ALL RENAMES REC-A THRU REC-B.
            """
        )
        records = copybook.parse(source)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].length, 5)

    def test_unnamed_filler_is_inferred(self):
        source = fixed(
            """
            01  REC.
                05  REC-A                   PIC X(2).
                05  PIC X(3).
            """
        )
        record = copybook.parse(source)[0]
        self.assertEqual(record.length, 5)
        self.assertEqual(
            [f.name for f in record.flatten(elementary_only=True)], ["REC-A", "FILLER"]
        )

    def test_edited_picture_with_a_period_is_not_split(self):
        record = copybook.parse(fixed("01  AMT PIC ZZ,ZZ9.99.\n"))[0]
        self.assertEqual(record.length, 9)

    def test_continuation_lines_are_folded(self):
        source = (
            " " * 7 + "01  REC.\n"
            + " " * 11 + "05  REC-LONG-NAME\n"
            + " " * 6 + "-" + " " * 4 + "    PIC X(7).\n"
        )
        record = copybook.parse(source)[0]
        self.assertEqual(record.length, 7)

    def test_unresolvable_redefines_warns_rather_than_crashing(self):
        source = fixed(
            """
            01  REC.
                05  REC-A                   PIC X(2).
                05  REC-B REDEFINES NOT-THERE
                                            PIC X(2).
            """
        )
        record = copybook.parse(source)[0]
        self.assertTrue(any("REDEFINES" in w for w in record.warnings), record.warnings)

    def test_empty_input_yields_no_records(self):
        self.assertEqual(copybook.parse(""), [])


if __name__ == "__main__":
    unittest.main()
