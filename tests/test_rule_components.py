import unittest

from direct_sheet1_parser import extract_sheet1_rows_from_markdown_table
from direct_sheet2_parser import extract_sheet2_rows_from_markdown_table
from target_row_filter import classify_sample


class RuleComponentTests(unittest.TestCase):
    def test_sample_classification(self):
        self.assertEqual(classify_sample(sample_id="BC"), "pristine")
        self.assertEqual(classify_sample(sample_id="BC-HNO3"), "acid")
        self.assertEqual(classify_sample(sample_id="BC-KOH"), "other")
        self.assertEqual(classify_sample(), "unknown")

    def test_sheet1_markdown_table(self):
        table = """| sample_id | acid_type | SSA_m2_g |
|---|---|---|
| BC-HNO3 | HNO3 | 412 |
"""
        rows = extract_sheet1_rows_from_markdown_table(table)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sample_id"], "BC-HNO3")
        self.assertEqual(rows[0]["acid_type"], "HNO3")
        self.assertEqual(rows[0]["SSA_m2_g"], "412")

    def test_sheet2_markdown_table(self):
        table = """| sample_id | pollutant_name | pH | T_K | Te_min | SLR_g_L |
|---|---|---|---|---|---|
| BC-HNO3 | U(VI) | 5 | 298 | 120 | 1 |
"""
        rows = extract_sheet2_rows_from_markdown_table(table)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["pollutant_name"], "U(VI)")
        self.assertEqual(rows[0]["T_K"], "298")


if __name__ == "__main__":
    unittest.main()

