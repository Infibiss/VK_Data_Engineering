import hashlib
import gzip
import json
import shutil
from common import ROOT, BUCKET, KEY, DATA_URI, s3

client = s3()
try:
    client.head_bucket(Bucket=BUCKET)
except client.exceptions.ClientError:
    client.create_bucket(Bucket=BUCKET)
path = ROOT / 'tmp/it_vacancies_2024.csv.gz'
original = ROOT / 'it_vacancies_2024.csv'
if not path.exists() or path.stat().st_mtime < original.stat().st_mtime:
    path.parent.mkdir(exist_ok=True)
    with original.open('rb') as source, gzip.open(path, 'wb', compresslevel=1) as packed:
        shutil.copyfileobj(source, packed, length=8 * 1024 * 1024)
digest = hashlib.file_digest(original.open('rb'), 'sha256').hexdigest()
with path.open('rb') as body:
    response = client.put_object(Bucket=BUCKET, Key=KEY, Body=body,
                                 ContentLength=path.stat().st_size,
                                 ContentType='application/gzip',
                                 Metadata={'source-sha256': digest,
                                           'source-bytes': str(original.stat().st_size)})
head = client.head_object(Bucket=BUCKET, Key=KEY)
output = {'data_uri': DATA_URI, 'http': response['ResponseMetadata']['HTTPStatusCode'],
          'original_bytes': original.stat().st_size, 'gzip_bytes': head['ContentLength'],
          'source_sha256': digest}
(ROOT / 'evidence/upload.json').write_text(json.dumps(output, ensure_ascii=False, indent=2))
print(json.dumps(output, ensure_ascii=False, indent=2))
