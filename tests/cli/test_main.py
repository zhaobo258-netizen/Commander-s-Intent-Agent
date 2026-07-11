from factory import __version__
from factory.cli.main import build_parser, main


def test_package_version_and_help(capsys):
    assert __version__ == "0.1.0"
    parser = build_parser()
    assert parser.prog == "commander-factory"
    assert main(["--version"]) == 0
    assert "0.1.0" in capsys.readouterr().out
