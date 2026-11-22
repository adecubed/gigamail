#!/bin/bash

# Delete the link to the binary
# update-alternatives --remove <name> <path>: 'path' must be the registered alternative binary,
# not the generic symlink — see https://man7.org/linux/man-pages/man1/update-alternatives.1.html
if type update-alternatives >/dev/null 2>&1; then
    update-alternatives --remove '${executable}' '/opt/${sanitizedProductName}/${executable}'
else
    rm -f '/usr/bin/${executable}'
fi

APPARMOR_PROFILE_DEST='/etc/apparmor.d/${executable}'

# Remove and unload apparmor profile.
if [ -f "$APPARMOR_PROFILE_DEST" ]; then
  # Unload the profile from the running kernel before deleting the file so the
  # policy is not left enforced until the next reboot.  Mirror the chroot guard
  # used in the after-install script — live AppArmor operations are not
  # meaningful inside a chroot.
  # https://wiki.debian.org/AppArmor/HowToUse
  if apparmor_status --enabled > /dev/null 2>&1; then
    if ! { [ -x '/usr/bin/ischroot' ] && /usr/bin/ischroot; } && hash apparmor_parser 2>/dev/null; then
      apparmor_parser --remove "$APPARMOR_PROFILE_DEST" || true
    fi
  fi
  rm -f "$APPARMOR_PROFILE_DEST"
fi
# ── GigaMail: the command line, only the links we made ───────────────────
for cmd in gigamail gigamail-server; do
  link="/usr/bin/$cmd"
  if [ -L "$link" ] && [ "$(readlink "$link")" = '/opt/${sanitizedProductName}/resources/bin/'"$cmd" ]; then
    rm -f "$link"
  fi
done

# -- GigaMail: the Codex entry of after-install, only if it is still ours --
# The bundled Python is gone by now: plain text tools. From the
# [mcp_servers.gigamail] header to the next table header, as
# codex_config._without_entry does. An upgrade runs this too, and the new
# version's after-install writes the entry again.
codex_cfg=/etc/codex/config.toml
if [ -f "$codex_cfg" ] && grep -qF 'command = "/opt/${sanitizedProductName}/resources/bin/gigamail-server"' "$codex_cfg"; then
  codex_tmp="$(mktemp)" && awk '
    /^[[:space:]]*\[[[:space:]]*mcp_servers[[:space:]]*\.[[:space:]]*("gigamail"|gigamail)[[:space:]]*(\.[^]]*)?\]/ { skip = 1; next }
    skip && /^[[:space:]]*\[/ { skip = 0 }
    !skip { print }
  ' "$codex_cfg" > "$codex_tmp" && cat "$codex_tmp" > "$codex_cfg"
  rm -f "$codex_tmp"
  if ! grep -q '[^[:space:]]' "$codex_cfg"; then
    rm -f "$codex_cfg" "$codex_cfg.gigamail-bak"
    rmdir /etc/codex 2>/dev/null || true
  fi
fi
