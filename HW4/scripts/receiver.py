import argparse
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
from pathlib import Path

from kazoo.exceptions import BadVersionError, NoNodeError

from coordination import HOSTS, atomic_write, connect, emit, first_error, packed


def accept(client, root, token, payload, fencing):
    if not fencing:
        return client.set(root + '/pointer', payload).version
    txn = client.transaction()
    txn.check(root + '/epoch', version=token)
    txn.check(root + '/leader', version=0)
    txn.set_data(root + '/pointer', payload)
    result = txn.commit()
    error = first_error(result)
    if error is not None:
        raise error
    return result[-1].version


def run(args):
    fencing = bool(int(os.environ.get('FENCING', '1')))
    client = connect(args.hosts)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, status, data):
            body = packed(data)
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path != '/result':
                return self.reply(404, {'error': 'NotFound'})
            try:
                writer = self.headers['X-Writer']
                token = int(self.headers['X-Epoch'])
                length = int(self.headers['Content-Length'])
                if writer not in ('primary', 'standby') or token <= 0 or not 0 < length <= 4_000_000:
                    raise ValueError
            except (TypeError, ValueError):
                return self.reply(400, {'error': 'InvalidPublication'})
            data = self.rfile.read(length)
            if len(data) != length:
                return self.reply(400, {'error': 'IncompleteBody'})
            name = f'{writer}-epoch{token}.csv'
            path = args.output / name
            if path.exists():
                return self.reply(409, {'error': 'DuplicateRequest'})
            value = {'writer': writer, 'epoch': token, 'file': name, 'sha256': sha256(data).hexdigest()}
            atomic_write(path, data)
            try:
                version = accept(client, args.root, token, packed(value), fencing)
            except (BadVersionError, NoNodeError) as exc:
                path.unlink()
                error = type(exc).__name__
                emit('rejected', writer=writer, epoch=token, error=error)
                return self.reply(409, {'error': error})
            emit('accepted', **value, pointer_version=version)
            self.reply(200, {'pointer_version': version, 'file': name})

    try:
        with HTTPServer(('127.0.0.1', 0), Handler) as server:
            emit('receiver_ready', port=server.server_port, fencing=int(fencing))
            server.serve_forever()
    finally:
        client.stop()
        client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--hosts', default=HOSTS)
    run(parser.parse_args())
