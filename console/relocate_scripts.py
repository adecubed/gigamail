"""Make the bundled Python's console scripts work wherever the app is installed.

pip writes into every script the absolute path of the Python that installed
it: on the CI runner that is D:\\a\\...\\python-embedded\\python.exe or
/Users/runner/.../python-embedded/bin/python3, a folder no user has. So
Scripts\\gigamail-server.exe and bin/gigamail-server failed on every
installed copy, and with them Codex and the console's agent bar, which start
the MCP server through that script.

Run with the bundled Python right after `pip install`:

    python relocate_scripts.py <python-embedded folder> [<PATH launchers folder>]

- Windows: the launcher .exe is distlib's, a stub followed by the shebang
  line and a zip. Its shebang becomes `#!<launcher_dir>\\..\\python.exe`,
  which the launcher resolves against its own folder (Scripts\\..).
- macOS: a text script. Its shebang becomes the /bin/sh trampoline pip itself
  uses for long paths, starting the python3 next to the script.

Exits with an error if a script still names the build folder afterwards.

Windows, with the second argument: copies of the `gigamail` and
`gigamail-server` launchers are written to that folder, which the app ships
as resources\\bin and the installer adds to the user's PATH. Scripts\\ itself
cannot go on PATH: it also holds pip and every dependency's commands. The
copies start `<launcher_dir>\\..\\python\\python.exe`, the bundled Python seen
from resources\\bin.
"""
import os
import sys

WIN_SHEBANG = b"#!<launcher_dir>\\..\\python.exe"
# From resources\bin, where the PATH launchers live, to resources\python.
WIN_BIN_SHEBANG = b"#!<launcher_dir>\\..\\python\\python.exe"
PATH_COMMANDS = ("gigamail", "gigamail-server")
# sh runs the first line, Python reads the rest as a string and moves on.
POSIX_SHEBANG = (
    "#!/bin/sh\n"
    "'''exec' \"$(dirname -- \"$0\")/python3\" \"$0\" \"$@\"\n"
    "' '''\n"
)


def relocate_exe(data: bytes, shebang: bytes = WIN_SHEBANG) -> bytes | None:
    """The launcher with its shebang pointing next to itself, or None when
    the file is not a distlib launcher."""
    zip_at = data.rfind(b"\nPK\x03\x04")
    if zip_at < 0:
        return None
    bang = data.rfind(b"#!", 0, zip_at)
    if bang < 0 or b"\n" in data[bang:zip_at]:
        return None
    if data[bang:zip_at] == shebang:
        return data
    return data[:bang] + shebang + data[zip_at:]


def write_path_launchers(root: str, out: str) -> list[str]:
    """Windows: the launchers of PATH_COMMANDS, copied from Scripts\\ into
    `out` with the shebang that reaches the bundled Python from
    resources\\bin. Returns the names written; raises when one is missing or
    is not a launcher, because the installer would put an empty folder on
    PATH."""
    os.makedirs(out, exist_ok=True)
    written = []
    for cmd in PATH_COMMANDS:
        name = cmd + ".exe"
        with open(os.path.join(root, "Scripts", name), "rb") as f:
            new = relocate_exe(f.read(), WIN_BIN_SHEBANG)
        if new is None:
            raise ValueError(f"{name} is not a distlib launcher")
        with open(os.path.join(out, name), "wb") as f:
            f.write(new)
        written.append(name)
    return written


def relocate_text(text: str) -> str | None:
    """The script with the sh trampoline, or None when it is not a Python
    script run by an absolute python path."""
    first, sep, rest = text.partition("\n")
    if text.startswith(POSIX_SHEBANG):
        return text
    if not sep or not first.startswith("#!/") or "python" not in first:
        return None
    return POSIX_SHEBANG + rest


def main(root: str, bin_out: str | None = None) -> int:
    root = os.path.abspath(root)
    win = os.path.isdir(os.path.join(root, "Scripts"))
    folder = os.path.join(root, "Scripts" if win else "bin")
    changed, stale = 0, []
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if os.path.islink(path) or not os.path.isfile(path):
            continue
        with open(path, "rb") as f:
            data = f.read()
        if win:
            if not name.lower().endswith(".exe"):
                continue
            new = relocate_exe(data)
        else:
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                continue
            fixed = relocate_text(text)
            new = fixed.encode("utf-8") if fixed is not None else None
        if new is None:
            continue
        if new != data:
            mode = os.stat(path).st_mode
            with open(path, "wb") as f:
                f.write(new)
            os.chmod(path, mode)
            changed += 1
        if root.encode() in new or root.replace("/", "\\").encode() in new:
            stale.append(name)
    print(f"  scripts relocated: {changed} in {folder}")
    if stale:
        print("  still naming the build folder: " + ", ".join(stale), file=sys.stderr)
        return 1
    if win and bin_out:
        names = write_path_launchers(root, bin_out)
        print(f"  PATH launchers: {', '.join(names)} in {os.path.abspath(bin_out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "python-embedded"),
                  sys.argv[2] if len(sys.argv) > 2 else None))
