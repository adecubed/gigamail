"""The OS secret store on macOS and Linux: Keychain, Secret Service.

Windows protects the accounts key with DPAPI (`win_dpapi`); this module is
the same idea for the other two systems, through the `keyring` package.
A secret stored here is tied to the user's login: copying the data folder
to another machine does not carry it along.

available() is False, and the caller keeps its own fallback, when:
- the platform is Windows (DPAPI is used there);
- `keyring` is not installed;
- keyring finds no real backend: a Linux server or container with no
  Secret Service, or only a plain-text backend, which would protect
  nothing;
- on Linux, there is no D-Bus session to reach the Secret Service through
  (an SSH session, a service): probing it there can block;
- GIGAMAIL_OS_KEYRING=0 (the test suite sets it, so it never writes to
  the Keychain of whoever runs it).
"""
import os
import sys

SERVICE = "gigamail"

# Plain-text and "fail"/"null" backends have a priority below 1: storing
# the key there would be no better than the file it replaces.
_MIN_PRIORITY = 1


def _backend():
    if sys.platform == "win32":
        return None
    if os.environ.get("GIGAMAIL_OS_KEYRING", "1").strip() == "0":
        return None
    if sys.platform.startswith("linux") and not os.environ.get(
        "DBUS_SESSION_BUS_ADDRESS"
    ):
        return None
    try:
        import keyring
    except Exception:
        return None
    try:
        backend = keyring.get_keyring()
        priority = float(getattr(backend, "priority", 0))
    except Exception:
        return None
    if priority < _MIN_PRIORITY:
        return None
    return backend


def available() -> bool:
    return _backend() is not None


def load(name: str):
    """The secret stored under `name`, or None if there is none.
    Raises OSError when the store cannot be reached."""
    backend = _backend()
    if backend is None:
        raise OSError("OS keyring not available")
    try:
        return backend.get_password(SERVICE, name)
    except Exception as e:
        raise OSError(f"OS keyring read failed: {e}") from e


def store(name: str, value: str) -> None:
    backend = _backend()
    if backend is None:
        raise OSError("OS keyring not available")
    try:
        backend.set_password(SERVICE, name, value)
    except Exception as e:
        raise OSError(f"OS keyring write failed: {e}") from e
