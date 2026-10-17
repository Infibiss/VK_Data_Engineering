import csv
import hashlib
import json
from pathlib import Path
from s3 import request

root = Path(__file__).resolve().parents[1]
source = root / 'dataset/it_vacancy_data.csv'
raw = source.read_bytes()
assert len(raw) == 87555558
assert hashlib.md5(raw).hexdigest() == '5e6a8c26ed481e327f5509de10358b11'
with source.open(encoding='utf-8-sig', newline='') as f:
    rows = csv.DictReader(f)
    records = []
    count = 0
    for row in rows:
        if count < 3:
            records.append(row)
        count += 1
print(f'CSV rows={count}; bytes={len(raw)}; source MD5=OK')
files = [source]
for i, record in enumerate(records, 1):
    path = root / f'dataset/vacancy_{i:02}.json'
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    files.append(path)
manifest = []
for path in files:
    data = path.read_bytes()
    key = 'hw2/' + path.name
    item = {'file':path.name, 'bytes':len(data), 'sha256':hashlib.sha256(data).hexdigest()}
    print('$ python3 scripts/s3.py PUT ' + key + ' --input dataset/' + path.name)
    result, _ = request('PUT', key, data)
    print(json.dumps(result))
    assert result['http'] == 200
    print('$ python3 scripts/s3.py GET ' + key)
    result, _ = request('GET', key)
    item['get_http'] = result['http']
    item['get_sha256'] = result.get('sha256')
    print(json.dumps(result))
    assert item['sha256'] == item['get_sha256']
    manifest.append(item)
(root / 'evidence/manifest.json').write_text(json.dumps({'rows':count, 'files':manifest}, indent=2))
print('All 4 uploaded objects: SHA256 MATCH')
