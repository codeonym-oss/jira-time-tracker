# The shell session every tape starts from (see README.md): a plain prompt, a scratch working
# directory, and the simulated Jira on 127.0.0.1:8765.
export PS1='$ ' PYTHONPATH=/vhs JTT_CONFIG_DIR=/tmp/jtt JTT_CREDENTIAL_BACKEND=file
mkdir -p /tmp/work && cd /tmp/work || return

jtt_serve() {
    python3 -m tests.jira_sim >/dev/null 2>&1 &
    disown
    until python3 -c "import socket; socket.create_connection(('127.0.0.1', 8765))" 2>/dev/null; do
        sleep 0.2
    done
    sleep 0.5
    clear
}

jtt_setup() {
    jtt_serve
    jtt login --url http://127.0.0.1:8765 --email robin.hale@example.com --token sim-token >/dev/null
    jtt init -p DEMO --field customfield_10016 --unit points >/dev/null
    jtt init -p OPS --field timeoriginalestimate --display-unit hours >/dev/null
    jtt init -p WEB --field customfield_10028 --unit points >/dev/null
    clear
}
