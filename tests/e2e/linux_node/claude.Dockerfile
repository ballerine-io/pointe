# A Linux node running real Claude Code, for tests/e2e/linux_node/real_claude.py. The checkout is mounted read-only at
# /pointe; ANTHROPIC_API_KEY comes only from `docker run -e`, never from the image or a file.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /usr/local/bin/uv
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends curl procps lsof git nodejs npm >/dev/null \
    && rm -rf /var/lib/apt/lists/* && npm install -g --silent @anthropic-ai/claude-code >/dev/null 2>&1 && claude --version
COPY pyproject.toml uv.lock /build/
RUN cd /build && UV_PROJECT_ENVIRONMENT=/state/node-env uv sync --locked --quiet --only-group node
ENV CLAUDE_VOICE_STATE=/state CLAUDE_VOICE_DAEMON_PORT=7966 PATH="/root/.local/bin:$PATH"
WORKDIR /work
CMD ["/state/node-env/bin/python", "/pointe/tests/e2e/linux_node/claude_driver.py"]
