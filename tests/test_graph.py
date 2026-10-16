"""Inventory extraction, including the false positives it has to avoid."""

import os
import unittest

from cobolkit import graph

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")
COBOL = os.path.join(FIXTURES, "cobol")


class TestCustupdt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.program = graph.analyze_file(os.path.join(COBOL, "CUSTUPDT.cbl"))

    def test_program_id(self):
        self.assertEqual(self.program.program_id, "CUSTUPDT")

    def test_static_calls_come_from_quoted_operands(self):
        self.assertEqual(sorted(self.program.static_calls), ["PAYCALC", "VALIDATE"])

    def test_a_call_inside_a_display_literal_is_not_a_call(self):
        # The fixture contains DISPLAY '... CALL THE OPERATOR ...'.
        self.assertNotIn("THE", self.program.dynamic_calls)
        self.assertNotIn("THE", self.program.static_calls)

    def test_dynamic_call_is_flagged_separately(self):
        self.assertEqual(self.program.dynamic_calls, ["WS-NEXT-PGM"])
        self.assertTrue(
            any("dynamic CALL" in risk for risk in self.program.risks),
            self.program.risks,
        )

    def test_copybooks_include_the_sql_precompiler_include(self):
        self.assertIn("CUSTREC", self.program.copybooks)
        self.assertIn("SQLCA", self.program.copybooks)

    def test_db2_tables_are_extracted_from_both_statement_shapes(self):
        self.assertEqual(self.program.sql_tables, ["CUSTOMER_ACCT"])

    def test_file_control_is_mapped_to_dd_names(self):
        self.assertEqual(
            sorted(self.program.files),
            [("CUSTOMER-FILE", "CUSTIN"), ("REPORT-FILE", "RPTOUT")],
        )

    def test_sql_select_is_not_mistaken_for_a_file_select(self):
        logical = [name for name, _ in self.program.files]
        self.assertNotIn("COUNT", logical)
        self.assertEqual(len(self.program.files), 2)

    def test_paragraphs_are_found_in_area_a_only(self):
        self.assertEqual(
            self.program.paragraphs,
            [
                "MAIN-CONTROL",
                "INITIALIZE-RUN",
                "PROCESS-CUSTOMERS",
                "VALIDATE-CUSTOMER",
                "APPLY-INTEREST",
                "FINALIZE-RUN",
                "WRITE-TOTALS",
                "UNUSED-DIAGNOSTIC",
            ],
        )

    def test_data_division_items_are_not_paragraphs(self):
        self.assertNotIn("WS-COUNTERS", self.program.paragraphs)
        self.assertNotIn("REPORT-LINE", self.program.paragraphs)

    def test_unperformed_paragraph_is_reported(self):
        self.assertEqual(self.program.dead_paragraphs, ["UNUSED-DIAGNOSTIC"])

    def test_stop_run_is_not_present_so_that_risk_is_not_raised(self):
        self.assertFalse(
            any("STOP RUN" in risk for risk in self.program.risks), self.program.risks
        )


class TestValidate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.program = graph.analyze_file(os.path.join(COBOL, "VALIDATE.cbl"))

    def test_cics_link_target_counts_as_a_call(self):
        self.assertIn("ERRLOGR", self.program.static_calls)

    def test_cics_verbs_are_collected(self):
        self.assertEqual(sorted(self.program.cics_commands), ["LINK", "WRITEQ"])

    def test_dynamic_call_via_working_storage(self):
        self.assertEqual(self.program.dynamic_calls, ["WS-EDIT-PGM"])

    def test_goto_statements_are_counted(self):
        self.assertEqual(self.program.goto_count, 3)


class TestPaycalc(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.program = graph.analyze_file(os.path.join(COBOL, "PAYCALC.cbl"))

    def test_a_leaf_program_calls_nothing(self):
        self.assertEqual(self.program.static_calls, [])
        self.assertEqual(self.program.dynamic_calls, [])

    def test_no_sql_or_cics(self):
        self.assertEqual(self.program.sql_tables, [])
        self.assertEqual(self.program.cics_commands, [])


class TestInventory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inventory = graph.analyze_tree(COBOL)

    def test_every_fixture_is_analyzed(self):
        self.assertEqual(
            sorted(p.program_id for p in self.inventory.programs),
            ["CUSTUPDT", "PAYCALC", "VALIDATE"],
        )

    def test_edges_record_their_kind(self):
        edges = set(self.inventory.edges)
        self.assertIn(("CUSTUPDT", "PAYCALC", "static"), edges)
        self.assertIn(("CUSTUPDT", "VALIDATE", "static"), edges)
        self.assertIn(("CUSTUPDT", "WS-NEXT-PGM", "dynamic"), edges)

    def test_calls_with_no_source_are_listed_as_missing(self):
        # ERRLOGR is reached by a CICS LINK from VALIDATE but has no source.
        self.assertIn("ERRLOGR", self.inventory.missing)
        self.assertNotIn("PAYCALC", self.inventory.missing)

    def test_dynamic_targets_are_not_reported_as_missing_programs(self):
        self.assertNotIn("WS-NEXT-PGM", self.inventory.missing)

    def test_uncalled_program_is_an_entry_point(self):
        self.assertEqual(self.inventory.orphans, ["CUSTUPDT"])

    def test_by_id_lookup(self):
        self.assertIn("PAYCALC", self.inventory.by_id)


class TestAnalyzerRobustness(unittest.TestCase):
    def test_program_id_falls_back_to_the_filename(self):
        program = graph.analyze("       DISPLAY 'HI'.\n", path="some/dir/ORPHAN.cbl")
        self.assertEqual(program.program_id, "ORPHAN")

    def test_empty_source_does_not_crash(self):
        program = graph.analyze("", path="EMPTY.cbl")
        self.assertEqual(program.source_lines, 0)
        self.assertEqual(program.static_calls, [])


if __name__ == "__main__":
    unittest.main()
