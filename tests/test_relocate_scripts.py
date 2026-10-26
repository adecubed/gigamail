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
