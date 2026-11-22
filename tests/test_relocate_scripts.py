"""console/relocate_scripts.py: the bundled scripts must not name the build folder."""
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("relocate_scripts", ROOT / "console" / "relocate_scripts.py")
rs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rs)

STUB = b"MZ launcher stub \x00\x01\x02"
ZIP = b"PK\x03\x04 zipped __main__.py"


def test_exe_shebang_points_next_to_the_launcher():
    old = STUB + b"#!D:\\a\\gigamail\\gigamail\\console\\python-embedded\\python.exe\n" + ZIP
    new = rs.relocate_exe(old)
    assert new == STUB + rs.WIN_SHEBANG + b"\n" + ZIP
    assert rs.relocate_exe(new) == new


def test_exe_without_appended_zip_is_left_alone():
    assert rs.relocate_exe(STUB + b"no archive here") is None


def test_text_script_gets_the_sh_trampoline():
    old = "#!/Users/runner/work/x/python-embedded/bin/python3\nimport sys\nfrom gigamail.server import main\n"
    new = rs.relocate_text(old)
    assert new == rs.POSIX_SHEBANG + "import sys\nfrom gigamail.server import main\n"
    assert rs.relocate_text(new) == new
    assert rs.relocate_text("#!/bin/sh\necho hi\n") is None


def test_trampoline_runs_the_python_next_to_the_script(tmp_path):
    if os.name == "nt":
        return
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "python3").symlink_to(sys.executable)
    script = bin_ / "hello"
    script.write_text("#!/build/machine/bin/python3\nimport sys\nprint('ran', sys.argv[1:])\n")
    script.chmod(0o755)
    assert rs.main(str(tmp_path)) == 0
    out = subprocess.run([str(script), "a", "b c"], capture_output=True, text=True, timeout=30)
    assert out.stdout.strip() == "ran ['a', 'b c']"


def test_path_launchers_reach_the_bundled_python_from_resources_bin(tmp_path):
    """The copies the installer puts on PATH live in resources\\bin, one
    folder away from resources\\python: their shebang names that path, and
    only the two documented commands are copied (not pip, not the rest)."""
    scripts = tmp_path / "python-embedded" / "Scripts"
    scripts.mkdir(parents=True)
    for name in ("gigamail.exe", "gigamail-server.exe", "gigamail-console-api.exe", "pip.exe"):
        (scripts / name).write_bytes(STUB + rs.WIN_SHEBANG + b"\n" + ZIP + name.encode())
    out = tmp_path / "win-bin"
    assert rs.write_path_launchers(str(tmp_path / "python-embedded"), str(out)) == ["gigamail.exe", "gigamail-server.exe"]
    assert sorted(p.name for p in out.iterdir()) == ["gigamail-server.exe", "gigamail.exe"]
    assert (out / "gigamail-server.exe").read_bytes() == (
        STUB + b"#!<launcher_dir>\\..\\python\\python.exe\n" + ZIP + b"gigamail-server.exe")
    # the launchers in Scripts keep their own shebang
    assert (scripts / "gigamail-server.exe").read_bytes().startswith(STUB + rs.WIN_SHEBANG + b"\n")


def test_path_launchers_fail_loudly_when_a_command_is_not_a_launcher(tmp_path):
    scripts = tmp_path / "python-embedded" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "gigamail.exe").write_bytes(STUB + b"no archive here")
    try:
        rs.write_path_launchers(str(tmp_path / "python-embedded"), str(tmp_path / "win-bin"))
    except ValueError as e:
        assert "gigamail.exe" in str(e)
    else:
        raise AssertionError("an empty folder would have gone on PATH")
