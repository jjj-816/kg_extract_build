import io
import zipfile
import unittest

from kg_extract_build.blind_review import build_blind_review_package


class BlindReviewPackageTests(unittest.TestCase):
    def test_package_is_anonymous_and_contains_expert_files(self):
        package, sample_count = build_blind_review_package([
            {
                "triplet_id": 99,
                "file_name": "长宁H3平台泡排工艺施工.md",
                "head": "100吨吊车",
                "head_type": "设备工具",
                "relation_name": "USED_FOR",
                "tail": "吊装作业",
                "tail_type": "作业活动",
                "evidence_sentence": "吊装作业选用100吨吊车。",
                "evidence_context": "施工时，吊装作业选用100吨吊车。",
            }
        ])
        self.assertEqual(sample_count, 1)
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {
                    "README_盲审说明.md",
                    "blind_review_form.csv",
                    "evidence_contexts.csv",
                    "blind_review_samples.md",
                },
            )
            content = "\n".join(
                archive.read(name).decode("utf-8-sig")
                for name in archive.namelist()
                if name.endswith(".csv")
            )
        self.assertIn("BR-0001", content)
        self.assertIn("DOC-001", content)
        self.assertNotIn("长宁H3平台泡排工艺施工.md", content)
        self.assertNotIn("99", content)


if __name__ == "__main__":
    unittest.main()
