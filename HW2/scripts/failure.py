"""Reversible disappearance of lab drive paths; keep original shards offline."""
import argparse
import hashlib
import json
from pathlib import Path
from s3 import request

root = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument('action', choices=['disable','restore','check'])
p.add_argument('count', type=int)
a = p.parse_args()
assert a.count in [0,1,2,3]
offline = root / 'offline'
offline.mkdir(exist_ok=True)
if a.action == 'disable':
    for i in range(1, a.count+1):
        drive, saved = root / f'volumes/disk{i}', offline / f'disk{i}'
        assert drive.is_dir() and not saved.exists()
        drive.rename(saved)
        drive.write_text('HW2: drive path unavailable; original data preserved offline.\n')
        print(f'$ mv volumes/disk{i} offline/disk{i}')
        print(f'$ touch volumes/disk{i}  # block auto-recreation')
elif a.action == 'restore':
    for i in range(1, a.count+1):
        drive, saved = root / f'volumes/disk{i}', offline / f'disk{i}'
        assert drive.is_file() and saved.is_dir()
        drive.unlink()
        saved.rename(drive)
        print(f'Restored disk{i}')
else:
    expected = json.loads((root / 'evidence/manifest.json').read_text())['files']
    results = []
    print(f'Unavailable drive paths: {a.count}/4')
    for i in range(1, a.count+1):
        try:
            list((root / f'volumes/disk{i}').iterdir())
        except NotADirectoryError:
            print(f'disk{i}: Not a directory (confirmed)')
        else:
            raise AssertionError('Drive still accessible')
    for entry in expected:
        key = 'hw2/' + entry['file']
        print(f'$ python3 scripts/s3.py GET {key}')
        result, _ = request('GET', key)
        result['sha256_match'] = result.get('sha256') == entry['sha256']
        results.append(result)
        print(f"HTTP {result['http']}; bytes={result['bytes']}; " +
              ('SHA256 MATCH' if result['sha256_match'] else f"error={result.get('error')}"))
    payload = b'{"test":"write-quorum","case":' + str(a.count).encode() + b'}\n'
    print(f'$ python3 scripts/s3.py PUT hw2/probe-{a.count}.json')
    result, _ = request('PUT', f'hw2/probe-{a.count}.json', payload)
    print(f"HTTP {result['http']}; " + ("write OK" if result['http'] == 200 else f"error={result.get('error')}"))
    results.append(result)
    (root / f'evidence/case-{a.count}.json').write_text(json.dumps(results, indent=2))
    if a.count <= 2:
        assert all(r['http'] == 200 and r['sha256_match'] for r in results[:-1])
    else:
        assert all(r['http'] != 200 for r in results[:-1])
    assert (result['http'] == 200) == (a.count < 2)
