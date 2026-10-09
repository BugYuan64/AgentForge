"""Revalidate complete M9 log transport and file-boundary evidence."""

import base64

import pytest

from agentforge.acceptance import checks


def test_log_and_xml_must_describe_the_same_execution(tmp_path):
    xml = tmp_path / "results.xml"
    log = tmp_path / "run.log"
    cases = ''.join(f'<testcase classname="tests.test_todos" name="{name}"/>'
                    for name in checks.EXPECTED_TESTS)
    raw = (f'<testsuite tests="5" failures="0" errors="0" skipped="0">{cases}'
           '</testsuite>').encode()
    xml.write_bytes(raw)
    log.write_bytes(b"AGENTFORGE_JUNIT_BASE64=" + base64.b64encode(raw) + b"\n")
    assert hasattr(checks, "validate_evidence"), "M10 requires public evidence validation"
    assert set(checks.validate_evidence(log, xml, 0).values()) == {"passed"}
    xml.write_bytes(raw + b"\n")
    with pytest.raises(ValueError, match="disagree"):
        checks.validate_evidence(log, xml, 0)


def test_complete_evidence_limit_and_hardlinks_are_rejected(tmp_path):
    import os

    from agentforge.reporting.evidence import read_regular

    file = tmp_path / "run.log"
    file.write_bytes(b"abcdef")
    with pytest.raises(ValueError, match="byte limit"):
        read_regular(tmp_path, "run.log", 5)
    os.link(file, tmp_path / "linked.log")
    with pytest.raises(ValueError, match="hard links"):
        read_regular(tmp_path, "linked.log", 10)


def test_complete_evidence_rejects_a_symbolic_link(tmp_path):
    from agentforge.reporting.evidence import read_regular

    file = tmp_path / "run.log"
    file.write_bytes(b"output")
    link = tmp_path / "linked.log"
    try:
        link.symlink_to(file)
    except OSError:
        pytest.skip("OS does not permit symlink creation")
    with pytest.raises(ValueError, match="links"):
        read_regular(tmp_path, "linked.log", 10)
