import argparse
import csv
from hashlib import sha256
import io
import json
import os
from pathlib import Path
from shlex import join
import signal
import subprocess
import sys
from time import monotonic, monotonic_ns, sleep
from uuid import uuid4

from coordination import HOSTS, atomic_write, connect, emit, packed

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT.parent / 'HW3/results/skills_2.csv'


def events(path, event):
    matches = []
    for line in path.read_text().splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if value.get('event') == event:
            matches.append(value)
    return matches


def await_event(process, path, event, seconds):
    deadline = monotonic() + seconds
    while monotonic() < deadline:
        matches = events(path, event)
        if matches:
            return matches[0]
        if process.poll() is not None:
            raise RuntimeError(f'{process.args[1]} exited {process.returncode}; see {path}')
        sleep(0.05)
    raise TimeoutError(f'{event}: see {path}')


def require_exit(process, seconds, path):
    code = process.wait(timeout=seconds)
    if code != 0:
        raise RuntimeError(f'Process exited {code}; see {path}')


def pointer(client, root):
    client.sync(root + '/pointer')
    value, stat = client.get(root + '/pointer')
    return {'version': stat.version, **(json.loads(value) if value else {})}


def run(args):
    unique = uuid4().hex[:8]
    label = args.label or ('with-fencing' if args.fencing else 'without-fencing')
    if not label or any(ch not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for ch in label):
        raise ValueError('Invalid run label')
    output = ROOT / 'results' / label
    work = ROOT / '.runtime/runs' / (label + '-' + unique)
    logs = ROOT / 'logs'
    output.mkdir(parents=True, exist_ok=False)
    work.mkdir(parents=True)
    logs.mkdir(exist_ok=True)
    root = '/hw4/' + label + '-' + unique
    gate = work / 'continue'
    expected = BASELINE.read_bytes()
    counts = list(csv.DictReader(io.StringIO(expected.decode())))
    baseline = {'pairs': len(counts), 'occurrences': sum(int(r['frequency']) for r in counts),
                'sha256': sha256(expected).hexdigest()}
    expected_summary = json.loads((BASELINE.parent / 'analysis.json').read_text())
    processes = []
    stopped = None

    def launch(name, script, arguments):
        path = logs / f'{label}-{name}.log'
        command = [f'scripts/{script}', *map(str, arguments)]
        print('$ ' + join(['python3', *command]), flush=True)
        with path.open('x') as stream:
            p = subprocess.Popen([sys.executable, *command], cwd=ROOT,
                                 stdout=stream, stderr=subprocess.STDOUT)
        processes.append(p)
        return p, path

    client = connect(args.hosts)
    try:
        client.ensure_path(root)
        for node in ('epoch', 'checkpoint', 'pointer'):
            client.create(root + '/' + node)
        emit('run_started', fencing=args.fencing, root=root, baseline=baseline)
        assert pointer(client, root) == {'version': 0}
        receiver, receiver_log = launch('receiver', 'receiver.py', [
            '--root', root, '--output', output.relative_to(ROOT), '--hosts', args.hosts,
        ])
        port = await_event(receiver, receiver_log, 'receiver_ready', 10)['port']
        worker_args = ['--root', root, '--sink', f'http://127.0.0.1:{port}',
                       '--work-dir', work.relative_to(ROOT), '--hosts', args.hosts]
        primary, primary_log = launch('primary', 'coordinator.py',
                                      worker_args + ['--writer', 'primary', '--gate', gate.relative_to(ROOT)])
        first = await_event(primary, primary_log, 'leader', 12)
        assert first['epoch'] == 1
        standby, standby_log = launch('standby', 'coordinator.py', worker_args + ['--writer', 'standby'])
        await_event(standby, standby_log, 'waiting', 12)
        boundary = await_event(primary, primary_log, 'pause_point', 25)
        client.sync(root + '/checkpoint')
        data, stat = client.get(root + '/checkpoint')
        original = json.loads(data)
        assert original['next_row'] == boundary['next_row'] == 65536
        assert original['epoch'] == 1 and stat.version == 2
        emit('checkpoint_at_pause', version=stat.version, **original)

        print(f'$ kill -STOP {primary.pid}', flush=True)
        paused_at = monotonic_ns()
        os.kill(primary.pid, signal.SIGSTOP)
        stopped = primary
        _, status = os.waitpid(primary.pid, os.WUNTRACED)
        assert os.WIFSTOPPED(status) and os.WSTOPSIG(status) == signal.SIGSTOP
        emit('paused', pid=primary.pid, signal='SIGSTOP', paused_at=paused_at)
        next_leader = await_event(standby, standby_log, 'leader', 32)
        assert next_leader['epoch'] == 2
        delay = (next_leader['at'] - paused_at) / 1e9
        assert delay > 0
        emit('handover', old='primary', new='standby', epoch=2, seconds=round(delay, 3))
        restored = await_event(standby, standby_log, 'restored', 12)
        assert restored['next_row'] == original['next_row'] and restored['from_epoch'] == 1
        emit('resumed_checkpoint', writer='standby', next_row=restored['next_row'],
             pairs=restored['pairs'], occurrences=restored['occurrences'])
        require_exit(standby, 35, standby_log)
        assert len(events(standby_log, 'published')) == 1
        initial = pointer(client, root)
        assert initial['version'] == 1 and initial['writer'] == 'standby'
        assert (output / initial['file']).read_bytes() == expected
        emit('pointer_before_continue', **initial)
        end_checkpoint, end_stat = client.get(root + '/checkpoint')
        end = json.loads(end_checkpoint)
        assert end['epoch'] == 2 and end['next_row'] == expected_summary['input_rows']
        assert end_stat.version == (end['next_row'] + 32767) // 32768

        sleep(max(0, args.pause_seconds - (monotonic_ns() - paused_at) / 1e9))
        gate.touch()
        print(f'$ kill -CONT {primary.pid}', flush=True)
        os.kill(primary.pid, signal.SIGCONT)
        stopped = None
        elapsed = (monotonic_ns() - paused_at) / 1e9
        emit('continued', pid=primary.pid, signal='SIGCONT', paused_seconds=round(elapsed, 3))
        require_exit(primary, 35, primary_log)

        latest = pointer(client, root)
        accepted = events(receiver_log, 'accepted')
        rejected = events(receiver_log, 'rejected')
        attempts = [*events(standby_log, 'publish_attempt'), *events(primary_log, 'publish_attempt')]
        assert len(attempts) == 2
        for attempt in attempts:
            assert attempt['input_rows'] == expected_summary['input_rows']
            assert attempt['selected_rows'] == expected_summary['selected_rows']
            assert (attempt['pairs'], attempt['occurrences']) == (baseline['pairs'], baseline['occurrences'])
        assert events(primary_log, 'checkpoint_rejected')
        final_checkpoint, final_stat = client.get(root + '/checkpoint')
        assert (final_checkpoint, final_stat.version) == (end_checkpoint, end_stat.version)
        if args.fencing:
            assert latest == initial and len(accepted) == len(rejected) == 1
            assert rejected[0]['error'] == 'BadVersionError'
            assert rejected[0]['writer'] == 'primary' and rejected[0]['epoch'] == 1
            assert not events(primary_log, 'published')
            assert events(primary_log, 'publication_rejected')[0]['error'] == 'BadVersionError'
        else:
            assert latest['version'] == 2 and latest['writer'] == 'primary' and latest['epoch'] == 1
            assert len(accepted) == 2 and not rejected
            assert len(events(primary_log, 'published')) == 1
        paths = sorted(p.name for p in output.glob('*.csv'))
        assert paths == sorted(r['file'] for r in accepted)
        for name in paths:
            assert (output / name).read_bytes() == expected
        emit('pointer_final', **latest)
        emit('comparison', hw3_equal=True, accepted=len(accepted),
             rejected=len(rejected), files=paths, **baseline)
        atomic_write(output / 'summary.json', packed({
            'fencing': args.fencing, 'root': root, 'handover_seconds': round(delay, 3),
            'pause_seconds': round(elapsed, 3), 'restored_from_row': original['next_row'],
            'checkpoint': end, 'baseline': baseline, 'pointer_before_continue': initial,
            'pointer_final': latest, 'accepted': len(accepted), 'rejected': len(rejected),
            'error': rejected[0]['error'] if rejected else None, 'hw3_equal': True,
        }) + b'\n')
    finally:
        if stopped and stopped.poll() is None:
            os.kill(stopped.pid, signal.SIGCONT)
        for p in reversed(processes):
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait(timeout=4)
        client.stop()
        client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--hosts', default=HOSTS)
    parser.add_argument('--label')
    parser.add_argument('--pause-seconds', type=float, default=40)
    parser.add_argument('--fencing', type=int, choices=[0, 1],
                        default=int(os.environ.get('FENCING', '1')))
    args = parser.parse_args()
    os.environ['FENCING'] = str(args.fencing)
    run(args)
