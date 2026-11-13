import argparse
import hashlib
import json
import tempfile

import boto3
from botocore.config import Config

parser = argparse.ArgumentParser()
parser.add_argument('--source', default='http://host.docker.internal:9100')
parser.add_argument('--target', default='http://host.docker.internal:9200')
args = parser.parse_args()

def client(endpoint, access, secret):
    return boto3.client('s3', endpoint_url=endpoint, aws_access_key_id=access,
                        aws_secret_access_key=secret, region_name='us-east-1',
                        config=Config(s3={'addressing_style': 'path'}))

source = client(args.source, 'hw3admin', 'hw3-local-secret')
target = client(args.target, 'hw5admin', 'hw5-local-secret')
bucket, key = 'hh-lake', 'raw/it_vacancies_2024.csv.gz'
if bucket not in [entry['Name'] for entry in target.list_buckets()['Buckets']]:
    target.create_bucket(Bucket=bucket)
hash_source = hashlib.sha256()
with tempfile.TemporaryFile() as file:
    with source.get_object(Bucket=bucket, Key=key)['Body'] as body:
        for chunk in iter(lambda: body.read(1024 * 1024), b''):
            hash_source.update(chunk)
            file.write(chunk)
    size = file.tell()
    file.seek(0)
    target.upload_fileobj(file, bucket, key)
hash_target = hashlib.sha256()
with target.get_object(Bucket=bucket, Key=key)['Body'] as body:
    for chunk in iter(lambda: body.read(1024 * 1024), b''):
        hash_target.update(chunk)
assert hash_source.digest() == hash_target.digest()
print(json.dumps({'source': args.source, 'target': args.target, 'object': f's3://{bucket}/{key}',
                  'bytes': size, 'source_sha256': hash_source.hexdigest(),
                  'target_sha256': hash_target.hexdigest(), 'identical': True}, indent=2))
