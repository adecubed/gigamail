# GigaMail MCP server — stdio transport.
#
# Used by directories (glama.ai) to build, start and introspect the server,
# and usable as-is by anyone who prefers a container:
#   docker build -t gigamail .
#   docker run -i --rm -v gigamail-data:/data gigamail
# The MCP client talks to the container over stdin/stdout (-i).
#
# Mailbox credentials never live in the image: connect an account with the
# CLI against the same volume, e.g.
#   docker run -it --rm -v gigamail-data:/data gigamail gigamail accounts add-imap
# Without accounts the server still starts and answers tools/list with all
# 24 tools; list_accounts returns [] — that is the expected empty state.

FROM python:3.12-slim

# Pure-Python dependencies; no system packages needed.
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir ".[all]"

# All data (accounts, approvals, audit, mail index) lives here — mount it.
ENV ADE_ROOT=/data \
    PYTHONUNBUFFERED=1
RUN useradd --create-home --uid 10001 gigamail \
    && mkdir -p /data && chown gigamail:gigamail /data
USER gigamail
VOLUME ["/data"]

CMD ["gigamail-server"]
