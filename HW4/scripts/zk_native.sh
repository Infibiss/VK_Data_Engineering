#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
runtime="$root/.runtime/native"
downloads="$root/.runtime/downloads"
nodes=(zk1 zk2 zk3)
zk_archive="$downloads/apache-zookeeper-3.9.6-bin.tar.gz"
zk_sha=e999626df06de30dc8bb53bb51da9bb786b1658406adafc6b92f104d72ca25e869f70a57c83a726f8b9558cc0fb519fc20f201aa5d6da09884bc4be5fe6dd3b0
java_archive="$downloads/temurin-17.0.21-jre.tar.gz"
java_sha=a5ab5bacd6e719d5a5570580ed14dceb2ed532208a39af927906b9742da1745e

valid_node() {
    case "$1" in zk1|zk2|zk3) ;; *) printf 'Unknown ZooKeeper node: %s\n' "$1" >&2; exit 2 ;; esac
}

java_17() {
    [[ -x "$1/bin/java" ]] && "$1/bin/java" -version 2>&1 | grep -E 'version "17[."]' >/dev/null
}

choose_java() {
    if [[ -n "${JAVA_HOME:-}" ]] && java_17 "$JAVA_HOME"; then
        export JAVA_HOME
        return
    fi
    JAVA_HOME="$runtime/java/Contents/Home"
    if ! java_17 "$JAVA_HOME"; then
        if [[ $(uname -s) != Darwin || $(uname -m) != arm64 || ! -f "$java_archive" ]]; then
            printf '%s\n' 'Set JAVA_HOME to an installed Java 17. On macOS arm64, the verified Temurin archive may also be placed in .runtime/downloads.' >&2
            exit 1
        fi
        printf '%s  %s\n' "$java_sha" "$java_archive" | shasum -a 256 --check
        mkdir -p "$runtime/java"
        tar -xzf "$java_archive" -C "$runtime/java" --strip-components=1
    fi
    java_17 "$JAVA_HOME" || { printf '%s\n' 'Java 17 verification failed' >&2; exit 1; }
    export JAVA_HOME
}

running() {
    local copy="$runtime/$1" pidfile pid
    pidfile="$copy/data/zookeeper_server.pid"
    [[ -f "$pidfile" ]] || return 1
    pid=$(cat "$pidfile")
    [[ "$pid" =~ ^[0-9]+$ ]] && ps -p "$pid" -o command= | grep -F "$copy/conf/zoo.cfg" >/dev/null
}

server() {
    local node=$1 action=$2 copy
    valid_node "$node"
    copy="$runtime/$node"
    ZOO_LOG_DIR="$copy/logs" ZOOPIDFILE="$copy/data/zookeeper_server.pid" \
        SERVER_JVMFLAGS='-Xms32m -Xmx160m' \
        "$copy/bin/zkServer.sh" "$action" "$copy/conf/zoo.cfg"
}

prepare() {
    mkdir -p "$runtime" "$downloads"
    if [[ ! -f "$zk_archive" ]]; then
        filename=apache-zookeeper-3.9.6-bin.tar.gz
        part=$(mktemp "$downloads/.zookeeper.XXXXXX")
        for base in https://downloads.apache.org https://archive.apache.org/dist; do
            if curl --fail --silent --show-error --location --connect-timeout 10 --max-time 120 \
                "$base/zookeeper/zookeeper-3.9.6/$filename" --output "$part" &&
                printf '%s  %s\n' "$zk_sha" "$part" | shasum -a 512 --check --status; then
                mv "$part" "$zk_archive"
                break
            fi
        done
        rm -f "$part"
        [[ -f "$zk_archive" ]] || { printf 'Place %s in %s\n' "$filename" "$downloads" >&2; exit 1; }
    fi
    printf '%s  %s\n' "$zk_sha" "$zk_archive" | shasum -a 512 --check
    for node in "${nodes[@]}"; do
        copy="$runtime/$node"
        mkdir -p "$copy" "$copy/data" "$copy/datalog" "$copy/logs"
        if [[ ! -x "$copy/bin/zkServer.sh" ]]; then
            tar -xzf "$zk_archive" -C "$copy" --strip-components=1
        fi
        if [[ -f "$copy/data/myid" && $(cat "$copy/data/myid") != "${node#zk}" ]]; then
            printf 'Incorrect myid: %s\n' "$copy/data/myid" >&2
            exit 1
        fi
        printf '%s\n' "${node#zk}" > "$copy/data/myid"
        sed -e "s#^dataDir=.*#dataDir=$copy/data#" \
            -e "s#^dataLogDir=.*#dataLogDir=$copy/datalog#" \
            "$root/config/native/$node/zoo.cfg" > "$copy/conf/zoo.cfg"
    done
}

[[ $# -ge 1 ]] || { printf '%s\n' 'Usage: zk_native.sh up|start|stop|status|ps|hosts|version|cli [node]' >&2; exit 2; }
action=$1
shift
case "$action" in
    hosts) printf '%s\n' 127.0.0.1:22181,127.0.0.1:22182,127.0.0.1:22183; exit ;;
    ps)
        for node in "${nodes[@]}"; do
            if running "$node"; then printf '%s running PID %s\n' "$node" "$(cat "$runtime/$node/data/zookeeper_server.pid")"
            else printf '%s stopped\n' "$node"; fi
        done
        exit
        ;;
esac
choose_java
case "$action" in
    up) prepare; for node in "${nodes[@]}"; do if ! running "$node"; then server "$node" start; fi; done ;;
    start)
        if [[ $# -eq 0 ]]; then set -- "${nodes[@]}"; fi
        for node in "$@"; do valid_node "$node"; if ! running "$node"; then server "$node" start; fi; done
        ;;
    stop)
        if [[ ${1:-} == -t ]]; then shift 2; fi
        if [[ $# -eq 0 ]]; then set -- "${nodes[@]}"; fi
        for node in "$@"; do valid_node "$node"; if running "$node"; then server "$node" stop; fi; done
        ;;
    status)
        if [[ $# -eq 0 ]]; then set -- "${nodes[@]}"; fi
        rc=0
        for node in "$@"; do
            valid_node "$node"
            printf '\n[%s; host 127.0.0.1:%s]\n' "$node" "$((22180 + ${node#zk}))"
            server "$node" status || rc=1
        done
        exit "$rc"
        ;;
    version)
        node=${1:-zk1}
        printf 'JAVA_HOME=%s\n' "$JAVA_HOME"
        "$JAVA_HOME/bin/java" -version
        server "$node" version
        ;;
    cli)
        node=${1:-zk1}
        valid_node "$node"
        if [[ $# -gt 0 ]]; then shift; fi
        exec "$runtime/$node/bin/zkCli.sh" -server "127.0.0.1:$((22180 + ${node#zk}))" "$@"
        ;;
    *) printf 'Unsupported action: %s\n' "$action" >&2; exit 2 ;;
esac
