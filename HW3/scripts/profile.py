import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time
from common import ROOT
import psutil


def trial(mode, attempt, inject_failure=False, chunk_rows=None):
    variant = f'{mode}-{chunk_rows}' if chunk_rows is not None else mode
    run_id = str(time.time_ns())
    name = f'{variant}-{attempt}-{run_id}' + ('-failure' if inject_failure else '')
    out = ROOT / 'tmp' / 'runs' / name
    out.mkdir(parents=True, exist_ok=True)
    logfile = ROOT / 'evidence' / f'{name}.log'
    if mode == 'duckdb':
        command = [sys.executable, str(ROOT / 'scripts/duckdb_job.py'), '--output-dir', str(out)]
    else:
        command = [sys.executable, str(ROOT / 'scripts/mapreduce.py'), '--engine', mode,
                   '--output-dir', str(out)]
        if inject_failure:
            command.append('--inject-failure')
        if chunk_rows is not None:
            command.extend(['--chunk-rows', str(chunk_rows)])
    peak = 0
    start = time.perf_counter()
    with logfile.open('w') as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
        monitored = psutil.Process(process.pid)
        while process.poll() is None:
            total = 0
            try:
                members = [monitored] + monitored.children(recursive=True)
            except psutil.NoSuchProcess:
                members = []
            for member in members:
                try:
                    total += member.memory_info().rss
                except psutil.NoSuchProcess:
                    pass
            peak = max(peak, total)
            if time.perf_counter() - start > 240:
                process.kill()
                raise RuntimeError(f'Trial exceeded 240 seconds: {logfile}')
            time.sleep(0.02)
        code = process.wait()
    elapsed = time.perf_counter() - start
    if code:
        raise RuntimeError(f'{mode} exit={code}: {logfile.read_text()[-6000:]}')
    record = {'mode': variant, 'attempt': attempt, 'run_id': run_id,
              'failure_injected': inject_failure,
              'seconds': elapsed, 'peak_rss_mib': peak / 1024**2,
              'output_dir': str(out.relative_to(ROOT)), 'log': str(logfile.relative_to(ROOT)),
              'command': command, 'timestamp_utc': datetime.now(timezone.utc).isoformat()}
    with (ROOT / 'evidence/profile.jsonl').open('a') as ledger:
        ledger.write(json.dumps(record, ensure_ascii=False) + '\n')
    print(json.dumps(record, ensure_ascii=False), flush=True)
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['baseline', 'combiner', 'fast', 'stream', 'duckdb'], required=True)
    parser.add_argument('--repeat', type=int, default=3)
    parser.add_argument('--start-at', type=int, default=1)
    parser.add_argument('--inject-failure', action='store_true')
    parser.add_argument('--chunk-rows', type=int)
    args = parser.parse_args()
    for attempt in range(args.start_at, args.start_at + args.repeat):
        print(f'Start {args.mode} attempt {attempt}', flush=True)
        trial(args.mode, attempt, args.inject_failure, args.chunk_rows)
