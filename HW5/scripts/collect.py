import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path


def digest(data):
    return hashlib.sha256(data).hexdigest()


def client(endpoint, mode):
    import boto3
    from botocore.config import Config
    return boto3.client(
        's3', endpoint_url=endpoint,
        aws_access_key_id=os.environ.get(mode.upper() + '_ACCESS_KEY', 'hw5admin' if mode == 'parallel' else 'hw3admin'),
        aws_secret_access_key=os.environ.get(mode.upper() + '_SECRET_KEY', 'hw5-local-secret' if mode == 'parallel' else 'hw3-local-secret'),
        region_name='us-east-1',
        config=Config(signature_version='s3v4', s3={'addressing_style': 'path'},
                      request_checksum_calculation='when_required',
                      response_checksum_validation='when_required'))


def parse_csv(data):
    reader = csv.DictReader(io.StringIO(data.decode('utf-8'), newline=''))
    rows = list(reader)
    return reader.fieldnames, rows


def main():
    parser = argparse.ArgumentParser(description='Collect HW5 S3 results and verify against HW3')
    parser.add_argument('--output-dir', type=Path, default=Path('/workspace/HW5/results'))
    parser.add_argument('--reference', type=Path,
                        default=Path('/workspace/HW3/results/skills_2.csv'))
    parser.add_argument('--parallel-endpoint', default='http://host.docker.internal:9200')
    parser.add_argument('--single-endpoint', default='http://host.docker.internal:9100')
    args = parser.parse_args()
    reference = args.reference.read_bytes()
    fields, reference_rows = parse_csv(reference)
    expected_top10 = io.StringIO(newline='')
    writer = csv.DictWriter(expected_top10, fieldnames=fields, lineterminator='\r\n')
    writer.writeheader()
    writer.writerows(reference_rows[:10])
    expected_top10 = expected_top10.getvalue().encode('utf-8')
    verification = {
        'reference': str(args.reference), 'reference_sha256': digest(reference),
        'reference_distinct_pairs': len(reference_rows),
        'reference_pair_occurrences': sum(int(row['frequency']) for row in reference_rows),
        'datasets': {},
    }
    contents = {}
    for mode, endpoint, prefix in (
        ('parallel', args.parallel_endpoint, 'hw5/parallel'),
        ('single', args.single_endpoint, 'hw5/calibrated'),
    ):
        s3 = client(endpoint, mode)
        directory = args.output_dir / mode
        directory.mkdir(parents=True, exist_ok=True)
        contents[mode] = {}
        for name in ('skills_2.csv', 'top10.csv', 'summary.json'):
            with s3.get_object(Bucket='hh-lake', Key=f'{prefix}/{name}')['Body'] as body:
                data = body.read()
            (directory / name).write_bytes(data)
            contents[mode][name] = data
        summary = json.loads(contents[mode]['summary.json'])
        data = contents[mode]['skills_2.csv']
        _, rows = parse_csv(data)
        info = {
            'endpoint': endpoint, 'prefix': f's3://hh-lake/{prefix}',
            'skills_2_sha256': digest(data),
            'top10_sha256': digest(contents[mode]['top10.csv']),
            'skills_2_exact_match': data == reference,
            'top10_exact_match': contents[mode]['top10.csv'] == expected_top10,
            'distinct_pairs': len(rows),
            'pair_occurrences': sum(int(row['frequency']) for row in rows),
            'input_rows': summary['input_rows'], 'selected_rows': summary['selected_rows'],
        }
        info['summary_consistent'] = (
            info['distinct_pairs'] == summary['distinct_pairs']
            and info['pair_occurrences'] == summary['pair_occurrences']
            and info['skills_2_sha256'] == summary['skills_2_sha256'])
        verification['datasets'][mode] = info
    verification['single_matches_hw3'] = verification['datasets']['single']['skills_2_exact_match']
    verification['parallel_matches_hw3'] = verification['datasets']['parallel']['skills_2_exact_match']
    verification['top10_matches_hw3'] = all(
        item['top10_exact_match'] for item in verification['datasets'].values())
    verification['single_parallel_equal'] = all(
        contents['single'][name] == contents['parallel'][name]
        for name in ('skills_2.csv', 'top10.csv'))
    verification['row_counts_match'] = all(
        verification['datasets']['single'][field] == verification['datasets']['parallel'][field]
        for field in ('input_rows', 'selected_rows', 'distinct_pairs', 'pair_occurrences'))
    verification['passed'] = all((
        verification['single_matches_hw3'], verification['parallel_matches_hw3'],
        verification['top10_matches_hw3'], verification['single_parallel_equal'],
        verification['row_counts_match'],
        all(item['summary_consistent'] for item in verification['datasets'].values()),
    ))
    (args.output_dir / 'verification.json').write_text(
        json.dumps(verification, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(verification, ensure_ascii=False, indent=2), flush=True)
    assert verification['passed'], 'HW5 outputs differ from HW3; see verification.json'


if __name__ == '__main__':
    main()
