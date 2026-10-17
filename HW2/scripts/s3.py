#!/usr/bin/env python3
"""Minimal SigV4 client for the local HW2 RustFS lab (standard library only)."""
import argparse
import datetime
import hashlib
import hmac
import http.client
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ACCESS = 'hw2admin'
SECRET = 'hw2-local-secret'
HOST = '127.0.0.1:9000'

def request(method, key, payload=b''):
    now = datetime.datetime.now(datetime.timezone.utc)
    stamp, day = now.strftime('%Y%m%dT%H%M%SZ'), now.strftime('%Y%m%d')
    path = '/' + key.lstrip('/')
    digest = hashlib.sha256(payload).hexdigest()
    headers = {'host': HOST, 'x-amz-content-sha256': digest, 'x-amz-date': stamp}
    signed = ';'.join(sorted(headers))
    canonical = '\n'.join([method, path, '', ''.join(f'{k}:{headers[k]}\n' for k in sorted(headers)), signed, digest])
    scope = f'{day}/us-east-1/s3/aws4_request'
    string = '\n'.join(['AWS4-HMAC-SHA256', stamp, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    signing = ('AWS4' + SECRET).encode()
    for part in [day, 'us-east-1', 's3', 'aws4_request']:
        signing = hmac.new(signing, part.encode(), hashlib.sha256).digest()
    signature = hmac.new(signing, string.encode(), hashlib.sha256).hexdigest()
    headers['Authorization'] = f'AWS4-HMAC-SHA256 Credential={ACCESS}/{scope}, SignedHeaders={signed}, Signature={signature}'
    if method == 'PUT':
        headers['Content-Length'] = str(len(payload))
    conn = http.client.HTTPConnection(HOST, timeout=40)
    try:
        conn.request(method, path, body=payload, headers=headers)
        response = conn.getresponse()
        body = response.read()
        result = {'method':method, 'key':key, 'http':response.status, 'bytes':len(body)}
        if 200 <= response.status < 300:
            if method == 'GET':
                result['sha256'] = hashlib.sha256(body).hexdigest()
        else:
            try:
                root = ET.fromstring(body)
                result['error'] = root.findtext('Code')
                result['message'] = root.findtext('Message')
            except ET.ParseError:
                result['error'] = body.decode(errors='replace')[:400]
        return result, body
    finally:
        conn.close()

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('method', choices=['PUT','GET','HEAD','DELETE'])
    p.add_argument('key')
    p.add_argument('--input', type=Path)
    p.add_argument('--output', type=Path)
    a = p.parse_args()
    result, body = request(a.method, a.key, a.input.read_bytes() if a.input else b'')
    if a.output and result['http'] == 200:
        a.output.write_bytes(body)
    if a.input:
        result['uploaded_bytes'] = a.input.stat().st_size
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if 200 <= result['http'] < 300 else 1)
