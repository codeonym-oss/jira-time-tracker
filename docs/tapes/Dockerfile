# VHS, plus jtt from a wheel of the working tree (record.sh builds it into .dist/).
FROM ghcr.io/charmbracelet/vhs:latest
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends python3 python3-venv >/dev/null \
 && python3 -m venv /opt/jtt && rm -rf /var/lib/apt/lists/*
COPY .dist/ /tmp/dist/
RUN /opt/jtt/bin/pip install -q /tmp/dist/*.whl
ENV PATH=/opt/jtt/bin:$PATH
