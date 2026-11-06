import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Event
from time import monotonic_ns, monotonic, time

from kazoo.client import KazooClient
from kazoo.exceptions import BadVersionError, NoNodeError, NodeExistsError
from kazoo.retry import KazooRetry


HOSTS = '127.0.0.1:22181,127.0.0.1:22182,127.0.0.1:22183'
SESSION_SECONDS = 10


def packed(data):
    return json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode()


def emit(event, **details):
    print(packed(dict(event=event, at=monotonic_ns(), wall=time(), **details)).decode(), flush=True)


def connect(hosts):
    client = KazooClient(hosts=hosts, timeout=SESSION_SECONDS,
                         command_retry=KazooRetry(max_tries=10, delay=0.1, max_delay=1))
    client.start(timeout=12)
    return client


def first_error(values):
    return next((value for value in values if isinstance(value, Exception)
                 and type(value).__name__ != 'RolledBackError'), None)


def atomic_write(path, data):
    path = Path(path)
    with NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        name = tmp.name
        try:
            tmp.write(data)
            tmp.flush()
            os.fsync(tmp.fileno())
            os.replace(name, path)
            fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            Path(name).unlink(missing_ok=True)


def acquire(client, root, writer):
    lease, epoch = root + '/leader', root + '/epoch'
    deadline = monotonic() + 80
    waiting = False
    while monotonic() < deadline:
        changed = Event()
        if client.exists(lease, watch=lambda _: changed.set()):
            if not waiting:
                emit('waiting', writer=writer)
                waiting = True
            changed.wait(2)
            continue
        _, stat = client.get(epoch)
        transaction = client.transaction()
        transaction.create(lease, writer.encode(), ephemeral=True)
        transaction.set_data(epoch, writer.encode(), version=stat.version)
        results = transaction.commit()
        error = first_error(results)
        if error is None:
            return stat.version + 1
        if not isinstance(error, (NodeExistsError, BadVersionError)):
            raise error
    raise TimeoutError('Leader election did not finish')


def checkpoint(client, root, epoch, version, manifest):
    transaction = client.transaction()
    transaction.check(root + '/epoch', version=epoch)
    transaction.check(root + '/leader', version=0)
    transaction.set_data(root + '/checkpoint', packed(manifest), version=version)
    results = transaction.commit()
    error = first_error(results)
    if error is None:
        return results[-1].version
    if isinstance(results[0], BadVersionError) or isinstance(results[1], NoNodeError):
        return None
    raise error
