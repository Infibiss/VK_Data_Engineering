#!/usr/bin/env python3

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import select
import shlex
import socket
import subprocess
import time
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
COMMAND = ["bash", "scripts/zk_ensemble.sh"]
PORTS = {"zk1": 22181, "zk2": 22182, "zk3": 22183}
MODE = re.compile(r"^Mode:\s+(leader|follower)\s*$", re.M)


def say(message):
    print(message, flush=True)


def stage(message):
    say(f"\n[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] {message}")


def invoke(*args, timeout=14, check=True):
    cmd = COMMAND + list(args)
    say("$ " + shlex.join(cmd))
    try:
        result = subprocess.run(
            cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=timeout, check=False,
        )
        code, output = result.returncode, result.stdout
    except subprocess.TimeoutExpired as error:
        code = 124
        output = (error.stdout or b"").decode("utf-8", "replace")
        say(f"[command timed out after {timeout} s]")
    if output:
        say(output.rstrip())
    say(f"[exit {code}]")
    if check and code != 0:
        raise RuntimeError(f"Command failed: {shlex.join(cmd)}")
    return code, output


def probe(node):
    try:
        with socket.create_connection(("127.0.0.1", PORTS[node]), timeout=0.7) as connection:
            connection.sendall(b"srvr")
            data = bytearray()
            while chunk := connection.recv(8192):
                data.extend(chunk)
        return data.decode("utf-8", "replace")
    except OSError as error:
        return f"{type(error).__name__}: {error}"


def show_probe(node, response):
    say(f"[4lw srvr, 127.0.0.1:{PORTS[node]}] {response.rstrip()}")


def wait_quorum(nodes, timeout=18):
    deadline = time.monotonic() + timeout
    while True:
        responses = {node: probe(node) for node in nodes}
        roles = {node: match.group(1) for node, response in responses.items()
                 if (match := MODE.search(response))}
        if sorted(roles.values()) == ["follower"] * (len(nodes) - 1) + ["leader"]:
            return roles
        if time.monotonic() >= deadline:
            raise RuntimeError(f"No leader and followers on {nodes}: {responses}")
        time.sleep(0.25)


def wait_no_quorum(node, timeout=18):
    deadline = time.monotonic() + timeout
    while True:
        response = probe(node)
        if "not currently serving requests" in response:
            return response
        if time.monotonic() >= deadline:
            raise RuntimeError(f"No explicit quorum-loss reply from {node}: {response!r}")
        time.sleep(0.25)


def quorum_demo():
    nodes = list(PORTS)
    marker = "/hw4-quorum-" + uuid4().hex[:8]
    payload = "committed-with-two-servers"

    stage("3/3: initial roles")
    roles = wait_quorum(nodes)
    invoke("ps")
    invoke("status")
    first = next(node for node, role in roles.items() if role == "leader")
    stopped = [first]
    try:
        stage(f"2/3: stop initial leader {first}, elect a new leader")
        invoke("stop", "-t", "5", first)
        survivors = [node for node in nodes if node != first]
        roles = wait_quorum(survivors)
        leader = next(node for node, role in roles.items() if role == "leader")
        follower = next(node for node, role in roles.items() if role == "follower")
        invoke("status", *survivors)
        _, created = invoke("cli", leader, "-timeout", "10000", "create", marker, payload)
        if f"Created {marker}" not in created:
            raise RuntimeError("The persistent znode was not created with two servers")
        _, readback = invoke("cli", follower, "-timeout", "10000", "get", marker)
        if payload not in readback.splitlines():
            raise RuntimeError("The second surviving node did not read the committed data")

        stage(f"1/3: stop {follower}; {leader} stays running without quorum")
        stopped.append(follower)
        invoke("stop", "-t", "5", follower)
        invoke("ps", "--all")
        show_probe(leader, wait_no_quorum(leader))
        invoke("status", leader, check=False)
        _, unavailable = invoke("cli", leader, "-timeout", "3000", "get", marker,
                                timeout=8, check=False)
        if payload in unavailable.splitlines() or "state:SyncConnected" in unavailable:
            raise RuntimeError("A normal client unexpectedly connected with one server")
    finally:
        stage("3/3: restart both stopped servers")
        invoke("start", *stopped)
        wait_quorum(nodes)
        invoke("status")

    _, recovered = invoke("cli", "zk1", "-timeout", "10000", "get", marker)
    if payload not in recovered.splitlines():
        raise RuntimeError("The committed znode was not retained after restoring quorum")
    stage(f"PASS: 3→2→1→3; persistent znode {marker} survived")


def read_until(process, target, timeout=12):
    data = bytearray()
    deadline = time.monotonic() + timeout
    while target not in data:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([process.stdout], [], [], remaining)[0]:
            raise RuntimeError(f"Owner CLI timed out waiting for {target!r}: {data!r}")
        chunk = os.read(process.stdout.fileno(), 4096)
        if not chunk:
            raise RuntimeError(f"Owner CLI closed before {target!r}: {data!r}")
        data.extend(chunk)
        say(chunk.decode("utf-8", "replace").rstrip())
    return data


def ephemeral_demo():
    wait_quorum(list(PORTS))
    marker = "/hw4-ephemeral-" + uuid4().hex[:8]
    command = COMMAND + ["cli", "zk2", "-timeout", "10000"]

    stage("Session A (zk2): open stock zkCli and create ephemeral znode")
    say("$ " + shlex.join(command))
    with subprocess.Popen(command, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, bufsize=0) as owner:
        try:
            read_until(owner, b"state:SyncConnected")
            create = f"create -e {marker} ephemeral-proof"
            say(f"[session A] {create}")
            owner.stdin.write((create + "\n").encode())
            read_until(owner, f"Created {marker}".encode())

            stage("Session B (zk1): observe the znode while its owner is connected")
            _, visible = invoke("cli", "zk1", "-timeout", "10000", "stat", marker)
            match = re.search(r"ephemeralOwner\s*=\s*(0x[0-9a-f]+)", visible, re.I)
            if not match or int(match.group(1), 16) == 0:
                raise RuntimeError("The observer did not find a nonzero ephemeral owner")

            stage("Close session A using the stock zkCli quit command")
            say("[session A] quit")
            owner.stdin.write(b"quit\n")
            tail, _ = owner.communicate(timeout=10)
            if tail:
                say(tail.decode("utf-8", "replace").rstrip())
            say(f"[session A exit {owner.returncode}]")
            if owner.returncode != 0:
                raise RuntimeError("Owner CLI did not close cleanly")

            stage("Independent observer: the ephemeral znode has disappeared")
            _, missing = invoke("cli", "zk1", "-timeout", "10000", "stat", marker,
                                check=False)
            if not re.search(r"node does not exist|nonode", missing, re.I):
                raise RuntimeError(f"Expected NoNode for {marker}")
        finally:
            if owner.poll() is None:
                owner.kill()
                owner.communicate(timeout=3)

    stage(f"PASS: {marker} existed with ephemeralOwner={match.group(1)} and disappeared on quit")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("demo", choices=("quorum", "ephemeral"))
    args = parser.parse_args()
    (quorum_demo if args.demo == "quorum" else ephemeral_demo)()


if __name__ == "__main__":
    main()
