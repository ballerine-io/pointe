# A Linux node, for tests/e2e/linux_node/run.sh. The checkout is mounted read-only at /pointe at run time.
# PORT_TOOL picks how the permission hook learns who listens on the node's port: lsof, ss (iproute2), or none (/proc).
FROM python:3.12-slim
ARG PORT_TOOL=none
COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /usr/local/bin/uv
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends curl procps \
      $([ "$PORT_TOOL" = lsof ] && echo lsof) $([ "$PORT_TOOL" = ss ] && echo iproute2) >/dev/null \
    && rm -rf /var/lib/apt/lists/* \
    && if [ "$PORT_TOOL" != lsof ]; then ! command -v lsof; fi \
    && if [ "$PORT_TOOL" != ss ]; then ! command -v ss; fi
# The node's environment, made the way bin/voice-node makes it, so the run itself needs no network.
COPY pyproject.toml uv.lock /build/
RUN cd /build && UV_PROJECT_ENVIRONMENT=/state/node-env uv sync --locked --quiet --only-group node \
    && ! /state/node-env/bin/python -c 'import pipecat' 2>/dev/null
ENV CLAUDE_VOICE_STATE=/state CLAUDE_VOICE_DAEMON_PORT=7966 UV_OFFLINE=1 PORT_TOOL=$PORT_TOOL
WORKDIR /work
CMD ["/state/node-env/bin/python", "/pointe/tests/e2e/linux_node/driver.py"]
