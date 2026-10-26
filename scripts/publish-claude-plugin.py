"""Move the claude-plugin branch to main when the Claude plugin changed.

The Claude directory tracks the `claude-plugin` branch, not `main`: it
records a new version for every commit on the branch it follows, and each
version is held for review again. So the branch moves only when
plugins/gigamail/ really changes. The version in plugin.json is ignored:
every release bumps it, and a bump alone is no reason for a new review.

Usage, from the repository root:

    python scripts/publish-claude-plugin.py          # report only
    python scripts/publish-claude-plugin.py --push   # move the branch

The branch is set to a commit of main, so it only ever fast-forwards.
"""
import argparse
import json
import subprocess
import sys

BRANCH = "claude-plugin"
PLUGIN = "plugins/gigamail"
MANIFEST = PLUGIN + "/.claude-plugin/plugin.json"


def git(*args, check=True):
    out = subprocess.run(["git", *args], capture_output=True, check=False)
    if check and out.returncode != 0:
        sys.exit(f"git {' '.join(args)}: {out.stderr.decode(errors='replace').strip()}")
    return out


def plugin_files(ref):
    """{path: bytes} of the plugin folder at `ref`."""
    names = git("ls-tree", "-r", "--name-only", ref, "--", PLUGIN).stdout.decode().split()
    return {name: git("show", f"{ref}:{name}").stdout for name in names}


def _without_version(data):
    manifest = json.loads(data.decode("utf-8"))
    manifest.pop("version", None)
    return manifest


def plugin_changed(old, new):
    """True when the plugin differs other than in plugin.json's version."""
    if set(old) != set(new):
        return True
    for name in new:
        if old[name] == new[name]:
            continue
        if name == MANIFEST and _without_version(old[name]) == _without_version(new[name]):
            continue
        return True
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--push", action="store_true", help="move the branch on origin")
    parser.add_argument("--ref", default="origin/main", help="commit to publish (default: origin/main)")
    args = parser.parse_args()

    git("fetch", "--quiet", "origin")
    target = git("rev-parse", args.ref).stdout.decode().strip()
    remote = f"origin/{BRANCH}"
    exists = git("rev-parse", "--verify", "--quiet", remote, check=False).returncode == 0

    if exists:
        current = git("rev-parse", remote).stdout.decode().strip()
        if git("merge-base", "--is-ancestor", current, target, check=False).returncode != 0:
            sys.exit(f"{remote} ({current[:7]}) is not an ancestor of {args.ref}: not moving it.")
        if not plugin_changed(plugin_files(current), plugin_files(target)):
            print(f"{PLUGIN} unchanged since {current[:7]}: {BRANCH} stays where it is.")
            return
        print(f"{PLUGIN} changed: {BRANCH} {current[:7]} -> {target[:7]}")
    else:
        print(f"{BRANCH} does not exist yet: it will start at {target[:7]}")

    if not args.push:
        print("Report only. Run again with --push to move the branch.")
        return
    git("push", "origin", f"{target}:refs/heads/{BRANCH}")
    print(f"Pushed {BRANCH} at {target[:7]}.")


if __name__ == "__main__":
    main()
