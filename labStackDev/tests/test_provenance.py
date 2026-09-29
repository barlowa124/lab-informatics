"""Shared provenance helper (docs/PROVENANCE.md, schema v1)."""
import json

import pytest

from lims import provenance as prov


def test_manifest_shape(tmp_path):
    f = tmp_path / "in.txt"
    f.write_text("data")
    m = prov.manifest("test-tool", inputs=[f], config={"a": 1},
                      packages=[])
    assert m["schema"] == "provenance/v1"
    assert m["input_sha256"][str(f)] == prov.sha256_file(f)
    assert m["config_sha256"] == prov.sha256_obj({"a": 1})
    assert "sha" in m["git"]


def test_canonical_config_hash_ignores_key_order():
    assert prov.sha256_obj({"b": 2, "a": 1}) == prov.sha256_obj(
        {"a": 1, "b": 2})


def test_verify_catches_tamper(tmp_path):
    f = tmp_path / "out.txt"
    f.write_text("v1")
    m = prov.manifest("t")
    prov.seal(m, [f])
    assert prov.verify(m) == []
    f.write_text("v2")
    assert prov.verify(m) == [
        f"output_sha256:{f}: sha256 mismatch"]


def test_missing_input_omitted(tmp_path):
    m = prov.manifest("t", inputs=[tmp_path / "nope"])
    assert m["input_sha256"] == {}


def test_dir_hash_stable(tmp_path):
    d = tmp_path / "d"
    (d / "sub").mkdir(parents=True)
    (d / "a.txt").write_text("a")
    (d / "sub" / "b.txt").write_text("b")
    h1 = prov.sha256_dir(d)
    assert h1 == prov.sha256_dir(d)
    (d / "a.txt").write_text("changed")
    assert prov.sha256_dir(d) != h1
