import json
from common import ROOT, BUCKET, s3

client = s3()
objects = []
for k in (1, 2, 3):
    path = ROOT / 'results' / f'skills_{k}.csv'
    key = f'results/variant9/skills_{k}.csv'
    with path.open('rb') as body:
        response = client.put_object(Bucket=BUCKET, Key=key, Body=body,
                                     ContentLength=path.stat().st_size,
                                     ContentType='text/csv; charset=utf-8')
    with client.get_object(Bucket=BUCKET, Key=key)['Body'] as body:
        assert body.read() == path.read_bytes(), key
    item = {'uri': f's3://{BUCKET}/{key}', 'bytes': path.stat().st_size,
            'http': response['ResponseMetadata']['HTTPStatusCode']}
    objects.append(item)
    print(f'{item["uri"]}: HTTP {item["http"]}; bytes={item["bytes"]}')
(ROOT / 'evidence/result-objects.json').write_text(json.dumps(objects, ensure_ascii=False, indent=2))
