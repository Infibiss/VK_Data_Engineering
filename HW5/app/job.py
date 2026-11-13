import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
import csv
import gzip
import hashlib
import io
from itertools import combinations
import json
import os
from pathlib import Path
import resource
from statistics import median
import sys
import tempfile
import time
from urllib.parse import urlsplit

HW3 = (Path(os.environ['HW3_SCRIPTS']) if os.environ.get('HW3_SCRIPTS')
       else Path(__file__).resolve().parents[2] / 'HW3/scripts')
sys.path.insert(0, str(HW3))
from common import is_variant, selected_row, python_rows, s3
from mapreduce import map_batch


def uri_join(prefix, name):
    return prefix.rstrip('/') + '/' + name


@contextmanager
def read_object(uri):
    if uri.startswith('s3://'):
        parsed = urlsplit(uri)
        with s3().get_object(Bucket=parsed.netloc, Key=parsed.path.lstrip('/'))['Body'] as body:
            yield body
    else:
        with Path(uri).open('rb') as body:
            yield body


def put_object(uri, data, content_type='application/octet-stream'):
    if uri.startswith('s3://'):
        parsed = urlsplit(uri)
        s3().put_object(Bucket=parsed.netloc, Key=parsed.path.lstrip('/'), Body=data,
                        ContentType=content_type)
    else:
        path = Path(uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('wb') as target:
            if hasattr(data, 'read'):
                import shutil
                shutil.copyfileobj(data, target)
            else:
                target.write(data)


def put_json(uri, value, compressed=False):
    data = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
    put_object(uri, gzip.compress(data, mtime=0) if compressed else data,
               'application/gzip' if compressed else 'application/json')


def read_json(uri, compressed=False):
    with read_object(uri) as body:
        return json.load(gzip.GzipFile(fileobj=body) if compressed else body)


def measure(start):
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    metrics = {'seconds': time.perf_counter() - start,
               'peak_rss_mib': rss / (1024 ** 2 if sys.platform == 'darwin' else 1024),
               'rss_source': 'resource.getrusage(RUSAGE_SELF).ru_maxrss'}
    if sys.platform == 'linux':
        try:
            metrics['cgroup_memory_peak_bytes'] = int(Path('/sys/fs/cgroup/memory.peak').read_text())
            metrics['cgroup_memory_peak_mib'] = metrics['cgroup_memory_peak_bytes'] / 1024 ** 2
            metrics['cgroup_memory_events'] = {key: int(value) for key, value in
                (line.split() for line in Path('/sys/fs/cgroup/memory.events').read_text().splitlines())}
        except (OSError, ValueError):
            pass
    return metrics


def split(args):
    counts = [0] * args.shards
    with tempfile.TemporaryDirectory(prefix='hw5-shards-') as temporary:
        from contextlib import ExitStack
        with ExitStack() as stack:
            streams = [stack.enter_context(gzip.open(Path(temporary) / f'{i}.csv.gz', 'wt',
                                                     encoding='utf-8', newline='', compresslevel=1))
                       for i in range(args.shards)]
            writers = None
            with read_object(args.input) as body:
                for index, row in enumerate(python_rows(body)):
                    if writers is None:
                        writers = [csv.DictWriter(stream, fieldnames=list(row)) for stream in streams]
                        for writer in writers:
                            writer.writeheader()
                    shard = index % args.shards
                    writers[shard].writerow(row)
                    counts[shard] += 1
            if writers is None:
                raise ValueError('Empty input')
        for index in range(args.shards):
            with (Path(temporary) / f'{index}.csv.gz').open('rb') as body:
                put_object(uri_join(args.shard_prefix, f'part-{index:04d}.csv.gz'), body,
                           'application/gzip')
    result = {'input': args.input, 'shards': args.shards, 'input_rows': sum(counts),
              'rows_per_shard': counts, 'partition': 'csv record index modulo shards'}
    put_json(uri_join(args.shard_prefix, 'manifest.json'), result)
    return result


def calculate(uri, chunk_rows):
    counts = Counter()
    salaries = defaultdict(list)
    stats = {'input_rows': 0, 'selected_rows': 0, 'with_skills': 0, 'salary_rows': 0}
    batch = []

    def consume():
        mapped = map_batch(batch, 'combiner', False)
        counts.update({stack: n for (region, stack), n in mapped.items()
                       if region == '' and len(stack) == 2})
        for row in batch:
            if row['salary'] is not None:
                for pair in combinations(row['skills'], 2):
                    salaries[pair].append(row['salary'])
        batch.clear()

    with read_object(uri) as body:
        for row in python_rows(body):
            stats['input_rows'] += 1
            if is_variant(row):
                selected = selected_row(row)
                batch.append(selected)
                stats['selected_rows'] += 1
                stats['with_skills'] += bool(selected['skills'])
                stats['salary_rows'] += selected['salary'] is not None
            if stats['input_rows'] % chunk_rows == 0:
                consume()
        consume()
    return counts, salaries, stats


def csv_data(rows):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=['skill_1', 'skill_2', 'frequency',
                                              'n_salary', 'median_salary'])
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode('utf-8')


def export(prefix, counts, salaries, stats):
    rows = [{'skill_1': pair[0], 'skill_2': pair[1], 'frequency': count,
             'n_salary': len(salaries[pair]),
             'median_salary': median(salaries[pair]) if salaries[pair] else ''}
            for pair, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]
    data = csv_data(rows)
    put_object(uri_join(prefix, 'skills_2.csv'), data, 'text/csv; charset=utf-8')
    put_object(uri_join(prefix, 'top10.csv'), csv_data(rows[:10]), 'text/csv; charset=utf-8')
    stats.update(distinct_pairs=len(rows), pair_occurrences=sum(counts.values()),
                 skills_2_sha256=hashlib.sha256(data).hexdigest(), top10=rows[:10])
    return stats


def run(args):
    start = time.perf_counter()
    if args.command == 'split':
        stats = split(args)
    elif args.command in ('single', 'worker'):
        uri = args.input if args.command == 'single' else uri_join(
            args.shard_prefix, f'part-{args.index:04d}.csv.gz')
        if args.command == 'worker':
            manifest = read_json(uri_join(args.shard_prefix, 'manifest.json'))
            if manifest['shards'] != args.shards:
                raise ValueError('Shard count does not match manifest')
        counts, salaries, stats = calculate(uri, args.chunk_rows)
        stats.update(command=args.command, input=uri, variant=9)
        if args.command == 'worker':
            if stats['input_rows'] != manifest['rows_per_shard'][args.index]:
                raise ValueError('Shard row count mismatch')
            stats.update(index=args.index, shards=args.shards)
            stats.update(measure(start))
            put_json(uri_join(args.output_prefix, f'part-{args.index:04d}.json.gz'),
                     {'stats': stats, 'pairs': [[list(pair), count, salaries[pair]]
                                               for pair, count in sorted(counts.items())]}, True)
        else:
            export(args.output_prefix, counts, salaries, stats)
    else:
        counts, salaries = Counter(), defaultdict(list)
        stats = {'command': 'reduce', 'variant': 9, 'input_rows': 0, 'selected_rows': 0,
                 'with_skills': 0, 'salary_rows': 0, 'shards': args.shards,
                 'worker_summaries': []}
        for index in range(args.shards):
            part = read_json(uri_join(args.parts_prefix, f'part-{index:04d}.json.gz'), True)
            if part['stats']['index'] != index or part['stats']['shards'] != args.shards:
                raise ValueError('Unexpected shard metadata')
            for pair, count, values in part['pairs']:
                counts[tuple(pair)] += count
                salaries[tuple(pair)].extend(values)
            for field in ('input_rows', 'selected_rows', 'with_skills', 'salary_rows'):
                stats[field] += part['stats'][field]
            stats['worker_summaries'].append(part['stats'])
        export(args.output_prefix, counts, salaries, stats)
    stats.update(measure(start))
    if args.command in ('single', 'reduce'):
        put_json(uri_join(args.output_prefix, 'summary.json'), stats)
    stats.update(measure(start))
    print(json.dumps(stats, ensure_ascii=False, allow_nan=False), flush=True)


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError('Must be positive')
    return number


def main():
    parser = argparse.ArgumentParser(description='HW3 variant 9 skill pairs on S3')
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('split', 'single', 'worker', 'reduce'):
        sub = commands.add_parser(command)
        if command in ('split', 'single'):
            sub.add_argument('--input', default='s3://hh-lake/raw/it_vacancies_2024.csv.gz')
        if command in ('split', 'worker'):
            sub.add_argument('--shard-prefix', required=True)
        if command != 'single':
            sub.add_argument('--shards', type=positive, default=4)
        if command != 'split':
            sub.add_argument('--output-prefix', required=True)
        if command in ('single', 'worker'):
            sub.add_argument('--chunk-rows', type=positive, default=2048)
        if command == 'worker':
            sub.add_argument('--index', type=int, default=os.environ.get('JOB_COMPLETION_INDEX', '0'))
        if command == 'reduce':
            sub.add_argument('--parts-prefix', required=True)
    args = parser.parse_args()
    if args.command == 'worker' and not 0 <= args.index < args.shards:
        parser.error('--index must be between 0 and shards - 1')
    run(args)


if __name__ == '__main__':
    main()
