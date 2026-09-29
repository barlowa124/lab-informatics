import json
import unittest

from lims.esign import (MEANINGS, sign, unsigned_rows, verify_signatures)
from lims.registry import LimsError, Registry

KEY = "test-key-not-a-secret"


def _reg_with_row():
    reg = Registry()
    reg.register_sample("S1", "rna")
    return reg


class SignTests(unittest.TestCase):
    def test_sign_and_verify(self):
        reg = _reg_with_row()
        sig = sign(reg, 1, "analyst@lab", "authored", key=KEY)
        self.assertEqual(len(sig), 64)
        rep = verify_signatures(reg, key=KEY)
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["n_signatures"], 1)

    def test_wrong_key_fails(self):
        reg = _reg_with_row()
        sign(reg, 1, "a", "authored", key=KEY)
        rep = verify_signatures(reg, key="other-key")
        self.assertFalse(rep["ok"])
        self.assertEqual(rep["bad"][0]["why"], "signature mismatch")

    def test_tampered_row_invalidates_signature(self):
        reg = _reg_with_row()
        sign(reg, 1, "a", "reviewed", key=KEY)
        reg.db.execute(
            "UPDATE audit_log SET action='deleted' WHERE seq=1")
        reg.db.commit()
        rep = verify_signatures(reg, key=KEY)
        self.assertFalse(rep["ok"])

    def test_sign_missing_row_refused(self):
        reg = _reg_with_row()
        with self.assertRaises(LimsError):
            sign(reg, 999, "a", "authored", key=KEY)

    def test_bad_meaning_refused(self):
        reg = _reg_with_row()
        with self.assertRaises(LimsError):
            sign(reg, 1, "a", "whatever", key=KEY)
        self.assertEqual(sorted(MEANINGS),
                         ["approved", "authored", "reviewed"])

    def test_no_key_raises(self):
        import os
        reg = _reg_with_row()
        saved = os.environ.pop("LIMS_SIGNING_KEY", None)
        try:
            with self.assertRaises(LimsError):
                sign(reg, 1, "a", "authored")
        finally:
            if saved is not None:
                os.environ["LIMS_SIGNING_KEY"] = saved

    def test_unsigned_rows_report(self):
        reg = _reg_with_row()
        reg.register_sample("S2", "dna")
        sign(reg, 1, "a", "authored", key=KEY)
        self.assertEqual(unsigned_rows(reg), [2])


class ReasonTests(unittest.TestCase):
    def test_reason_lands_in_chain(self):
        reg = Registry()
        reg.create_experiment("E1", "demo")
        reg.transition("E1", "queued", reason="batch window opened")
        row = reg.db.execute(
            "SELECT detail FROM audit_log WHERE action='transition'"
        ).fetchone()
        self.assertEqual(json.loads(row["detail"])["reason"],
                         "batch window opened")
        self.assertTrue(reg.verify_audit_chain()["ok"])

    def test_reason_optional(self):
        reg = Registry()
        reg.create_experiment("E1", "demo")
        reg.transition("E1", "queued")
        row = reg.db.execute(
            "SELECT detail FROM audit_log WHERE action='transition'"
        ).fetchone()
        self.assertNotIn("reason", json.loads(row["detail"]))


if __name__ == "__main__":
    unittest.main()
