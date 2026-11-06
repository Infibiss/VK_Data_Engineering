import argparse
import json
from pathlib import Path
from time import monotonic, sleep
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from coordination import HOSTS, SESSION_SECONDS, acquire, atomic_write, checkpoint, connect, emit
from pair_job import BUCKET, KEY, PairJob, batches, s3


def scan(source, etag, args, client, epoch, job, version, limit=None):
    response = source.get_object(Bucket=BUCKET, Key=KEY, IfMatch=etag)
    if response['ETag'] != etag:
        response['Body'].close()
        raise ValueError('S3 object changed during calculation')
    with response['Body'] as body:
        for cursor, rows in batches(body, args.chunk_rows, job.input_rows):
            job.add(cursor, rows)
            if version is not None:
                name = f'{epoch}-{cursor}.json.gz'
                path = args.work_dir / name
                atomic_write(path, job.snapshot(etag))
                manifest = {'next_row': cursor, 'file': name, 'etag': etag, 'epoch': epoch}
                version = checkpoint(client, args.root, epoch, version, manifest)
                if version is None:
                    path.unlink()
                    emit('checkpoint_rejected', epoch=epoch, next_row=cursor)
                else:
                    emit('checkpoint', epoch=epoch, next_row=cursor, version=version,
                         pairs=len(job.counts), occurrences=job.counts.total())
            if limit is not None and cursor >= limit:
                return version
    if limit is not None:
        raise RuntimeError('CSV ended before the pause point')
    return version


def publish(args, epoch, job):
    emit('publish_attempt', writer=args.writer, epoch=epoch, input_rows=job.input_rows,
         selected_rows=job.selected_rows, pairs=len(job.counts), occurrences=job.counts.total())
    req = Request(args.sink + '/result', job.csv(), headers={
        'Content-Type': 'text/csv; charset=utf-8',
        'X-Writer': args.writer,
        'X-Epoch': str(epoch),
    })
    try:
        with urlopen(req, timeout=15) as response:
            emit('published', writer=args.writer, epoch=epoch, message='записал результат',
                 **json.load(response))
    except HTTPError as exc:
        if exc.code != 409:
            raise
        emit('publication_rejected', writer=args.writer, epoch=epoch, **json.load(exc))


def run(args):
    client = connect(args.hosts)
    try:
        emit('connected', writer=args.writer, session_timeout=SESSION_SECONDS,
             session_id=hex(client.client_id[0]))
        epoch = acquire(client, args.root, args.writer)
        emit('leader', writer=args.writer, epoch=epoch)
        source = s3()
        etag = source.head_object(Bucket=BUCKET, Key=KEY)['ETag']
        manifest, stat = client.get(args.root + '/checkpoint')
        version = stat.version
        if manifest:
            saved = json.loads(manifest)
            job = PairJob.restore((args.work_dir / saved['file']).read_bytes(), etag)
            if job.input_rows != saved['next_row'] or saved['etag'] != etag:
                raise ValueError('Checkpoint and its manifest disagree')
            emit('restored', writer=args.writer, epoch=epoch, from_epoch=saved['epoch'],
                 next_row=job.input_rows, pairs=len(job.counts), occurrences=job.counts.total())
        else:
            job = PairJob()
        if args.gate:
            if job.input_rows:
                raise RuntimeError('Pause point requires a new job')
            version = scan(source, etag, args, client, epoch, job, version, 2 * args.chunk_rows)
            if version is None:
                raise RuntimeError('Pause point must have a committed checkpoint')
            emit('pause_point', writer=args.writer, epoch=epoch, next_row=job.input_rows)
            deadline = monotonic() + 95
            while not args.gate.exists():
                if monotonic() >= deadline:
                    raise TimeoutError('Pause point was not released')
                sleep(0.05)
            emit('resumed', writer=args.writer, epoch=epoch, next_row=job.input_rows)
            client.retry(client.get, args.root + '/epoch')
        scan(source, etag, args, client, epoch, job, version)
        publish(args, epoch, job)
    finally:
        client.stop()
        client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--writer', choices=['primary', 'standby'], required=True)
    parser.add_argument('--root', required=True)
    parser.add_argument('--sink', required=True)
    parser.add_argument('--work-dir', type=Path, required=True)
    parser.add_argument('--gate', type=Path)
    parser.add_argument('--hosts', default=HOSTS)
    parser.add_argument('--chunk-rows', type=int, default=32768)
    run(parser.parse_args())
