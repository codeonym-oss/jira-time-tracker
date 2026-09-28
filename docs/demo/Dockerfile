# VHS plus the released jtt from PyPI. See README.md in this folder.
FROM ghcr.io/charmbracelet/vhs:latest
ARG JTT_VERSION=0.1.0
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends python3 python3-venv >/dev/null \
 && python3 -m venv /opt/jtt && /opt/jtt/bin/pip install -q "jira-time-tracker==${JTT_VERSION}" \
 && rm -rf /var/lib/apt/lists/*
ENV PATH=/opt/jtt/bin:$PATH JTT_CREDENTIAL_BACKEND=file JTT_CONFIG_DIR=/tmp/jtt
