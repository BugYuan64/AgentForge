import pytest

from agentforge.cli import main


def test_demo_command_shows_success_and_cancellation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["demo"])

    assert exit_code == 0
    assert capsys.readouterr().out.splitlines() == [
        "demo-success: pending",
        "demo-success: succeeded",
        "demo-cancel: pending",
        "demo-cancel: cancelled",
    ]
