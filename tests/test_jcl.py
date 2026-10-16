"""JCL parsing: continuations, dataset direction and lineage."""

import os
import unittest

from cobolkit import jcl

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")
CUSTNITE = os.path.join(FIXTURES, "jcl", "CUSTNITE.jcl")


class TestCustnite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.job = jcl.parse_file(CUSTNITE)

    def test_job_name_comes_from_the_job_card(self):
        self.assertEqual(self.job.name, "CUSTNITE")

    def test_all_steps_are_found(self):
        self.assertEqual([s.name for s in self.job.steps], ["STEP010", "STEP020", "STEP030"])

    def test_programs_per_step(self):
        self.assertEqual(self.job.programs, ["CUSTUPDT", "CUSTSORT", "CUSTRPT"])

    def test_conditional_step_is_flagged(self):
        by_name = {s.name: s for s in self.job.steps}
        self.assertTrue(by_name["STEP020"].conditional)
        self.assertFalse(by_name["STEP030"].conditional)

    def test_continuation_does_not_split_a_disp_operand(self):
        # DISP=(NEW,CATLG,DELETE) is split across cards in the fixture.
        step = self.job.steps[0]
        rpt = next(d for d in step.datasets if d.ddname == "RPTOUT")
        self.assertEqual(rpt.disp, "NEW")
        self.assertEqual(rpt.direction, "output")
        self.assertEqual(rpt.dsn, "PROD.CUST.RPT(+1)")

    def test_shr_is_input(self):
        step = self.job.steps[0]
        custin = next(d for d in step.datasets if d.ddname == "CUSTIN")
        self.assertEqual(custin.direction, "input")
        self.assertEqual(custin.dsn, "PROD.CUST.MASTER(0)")

    def test_sysout_is_classified_separately(self):
        step = self.job.steps[0]
        sysout = next(d for d in step.datasets if d.ddname == "SYSOUT")
        self.assertEqual(sysout.direction, "sysout")
        self.assertIsNone(sysout.dsn)

    def test_inline_data_is_recognized_and_its_body_skipped(self):
        step = self.job.steps[0]
        sysin = next(d for d in step.datasets if d.ddname == "SYSIN")
        self.assertEqual(sysin.direction, "inline")
        # The control cards must not have become steps or DD statements.
        self.assertEqual(len(self.job.steps), 3)
        ddnames = [d.ddname for s in self.job.steps for d in s.datasets]
        self.assertNotIn("RUNMODE=NIGHTLY", ddnames)

    def test_temporary_dataset_is_detected(self):
        step = self.job.steps[0]
        temp = next(d for d in step.datasets if d.ddname == "CUSTOUT")
        self.assertTrue(temp.temporary)
        self.assertEqual(temp.direction, "output")

    def test_generation_datasets_are_detected(self):
        generations = {
            d.dsn for s in self.job.steps for d in s.datasets if d.generation
        }
        self.assertEqual(
            generations,
            {"PROD.CUST.MASTER(0)", "PROD.CUST.RPT(+1)", "PROD.CUST.SORTED(+1)"},
        )

    def test_lineage_links_producer_to_consumer(self):
        self.assertEqual(
            self.job.lineage(),
            [
                ("STEP010", "&&TEMPCUST", "STEP020"),
                ("STEP020", "PROD.CUST.SORTED(+1)", "STEP030"),
            ],
        )

    def test_comment_cards_are_ignored(self):
        self.assertNotIn(None, [s.name for s in self.job.steps])

    def test_inputs_and_outputs_exclude_sysout_and_inline(self):
        step = self.job.steps[0]
        self.assertEqual(
            sorted(d.ddname for d in step.outputs), ["CUSTOUT", "RPTOUT"]
        )
        self.assertEqual(sorted(d.ddname for d in step.inputs), ["CUSTIN", "STEPLIB"])


class TestJclEdges(unittest.TestCase):
    def test_procedure_invocation_by_keyword(self):
        job = jcl.parse("//S1 EXEC PROC=MYPROC\n")
        self.assertEqual(job.steps[0].procedure, "MYPROC")
        self.assertIsNone(job.steps[0].program)

    def test_procedure_invocation_positionally(self):
        job = jcl.parse("//S1 EXEC MYPROC\n")
        self.assertEqual(job.steps[0].procedure, "MYPROC")

    def test_dd_before_any_exec_warns(self):
        job = jcl.parse("//ORPHAN DD DSN=A.B,DISP=SHR\n")
        self.assertTrue(job.warnings)
        self.assertEqual(job.steps, [])

    def test_conditional_constructs_warn(self):
        job = jcl.parse(
            "//S1 EXEC PGM=A\n"
            "// IF RC = 0 THEN\n"
            "//S2 EXEC PGM=B\n"
            "// ENDIF\n"
        )
        self.assertTrue(any("conditional" in w for w in job.warnings), job.warnings)

    def test_dsname_spelling_is_accepted(self):
        job = jcl.parse("//S1 EXEC PGM=A\n//D1 DD DSNAME=X.Y,DISP=SHR\n")
        self.assertEqual(job.steps[0].datasets[0].dsn, "X.Y")

    def test_unnamed_step_gets_a_generated_name(self):
        job = jcl.parse("//       EXEC PGM=A\n")
        self.assertEqual(job.steps[0].name, "STEP001")

    def test_empty_input(self):
        job = jcl.parse("")
        self.assertEqual(job.steps, [])


if __name__ == "__main__":
    unittest.main()
