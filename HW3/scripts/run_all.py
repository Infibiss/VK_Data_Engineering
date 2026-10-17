import argparse
from datetime import datetime
from pathlib import Path
import subprocess
import sys
from common import ROOT


def invoke(script, *arguments):
    command = [sys.executable, str(ROOT / 'scripts' / script), *arguments]
    print('$ python3 scripts/' + script + ' ' + ' '.join(arguments), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--skip-upload', action='store_true')
    parser.add_argument('--confirm-only', action='store_true')
    args = parser.parse_args()
    (ROOT / 'tmp').mkdir(exist_ok=True)
    (ROOT / 'evidence').mkdir(exist_ok=True)
    if not args.confirm_only:
        ledger = ROOT / 'evidence/profile.jsonl'
        if ledger.exists():
            ledger.rename(ROOT / 'tmp' / f'profile-archive-{datetime.now():%Y%m%d-%H%M%S-%f}.jsonl')
        if not args.skip_upload:
            invoke('upload.py')
        for mode in ('baseline', 'combiner', 'fast'):
            invoke('profile.py', '--mode', mode, '--repeat', '3')
        invoke('profile.py', '--mode', 'fast', '--chunk-rows', '2048', '--repeat', '3')
        invoke('profile.py', '--mode', 'duckdb', '--repeat', '3')
        invoke('profile.py', '--mode', 'stream', '--repeat', '3')
    invoke('profile.py', '--mode', 'baseline', '--repeat', '1', '--start-at', '4')
    invoke('profile.py', '--mode', 'fast', '--chunk-rows', '2048', '--repeat', '1', '--start-at', '4')
    invoke('profile.py', '--mode', 'stream', '--repeat', '1', '--start-at', '4')
    invoke('profile.py', '--mode', 'fast', '--chunk-rows', '2048', '--repeat', '1', '--inject-failure')
    invoke('profile.py', '--mode', 'stream', '--repeat', '1', '--inject-failure')
    invoke('analyze.py')
    invoke('publish.py')


if __name__ == '__main__':
    main()
