from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
import argparse
from itertools import combinations, islice
import json
import os
from pathlib import Path
import time

from common import (ROOT, BUCKET, KEY, DATA_URI, FIELDS, ROLE, PATTERN, REGIONS,
                    is_variant, selected_row, python_rows, s3)
from aggregates import pay_statistics


def map_batch(rows, engine, fail):
    if fail:
        os._exit(23)
    emitted = [] if engine == 'baseline' else Counter()
    for row in rows:
        places = ('', row['area']) if row['area'] in REGIONS else ('',)
        for k in (1, 2, 3):
            for stack in combinations(row['skills'], k):
                for region in places:
                    key = (region, stack)
                    if engine == 'baseline':
                        emitted.append((key, 1))
                    else:
                        emitted[key] += 1
    return emitted


def batches(body, engine, size, stats):
    if engine == 'fast':
        import pandas as pd
        for frame in pd.read_csv(body, compression='gzip', usecols=FIELDS,
                                 chunksize=size, dtype=str, na_filter=False,
                                 encoding='utf-8-sig'):
            stats['input_rows'] += len(frame)
            keep = frame['role'].eq(ROLE) & frame['name'].str.lower().str.contains(PATTERN, regex=True)
            yield [selected_row(r) for r in frame.loc[keep].to_dict('records') if is_variant(r)]
    else:
        rows = iter(python_rows(body))
        if engine == 'stream':
            while True:
                count = 0
                selected = []
                for row in islice(rows, size):
                    count += 1
                    if is_variant(row):
                        selected.append(selected_row(row))
                if not count:
                    break
                stats['input_rows'] += count
                yield selected
            return
        while block := list(islice(rows, size)):
            stats['input_rows'] += len(block)
            yield [selected_row(r) for r in block if is_variant(r)]


def run(args):
    begun = time.perf_counter()
    client = s3()
    response = client.get_object(Bucket=BUCKET, Key=KEY)
    stats = {'engine': args.engine, 'data_uri': DATA_URI, 'input_rows': 0,
             'compressed_bytes': response['ContentLength'], 'chunk_rows': args.chunk_rows,
             'retries': 0, 'mapper_exit_code': None}
    result = Counter()
    selected = []
    pool = ProcessPoolExecutor(max_workers=1)
    try:
        with response['Body'] as body:
            for batch_id, batch in enumerate(batches(body, args.engine, args.chunk_rows, stats)):
                selected.extend(batch)
                fail = args.inject_failure and batch_id == 0
                try:
                    mapped = pool.submit(map_batch, batch, args.engine, fail).result()
                except BrokenProcessPool:
                    if not fail:
                        raise
                    stats['retries'] += 1
                    stats['mapper_exit_code'] = 23
                    print(f'mapper task={batch_id}: process exited 23; retry=1', flush=True)
                    pool.shutdown(wait=True, cancel_futures=True)
                    pool = ProcessPoolExecutor(max_workers=1)
                    mapped = pool.submit(map_batch, batch, args.engine, False).result()
                if args.engine == 'baseline':
                    for key, value in mapped:
                        result[key] += value
                else:
                    result.update(mapped)
    finally:
        pool.shutdown(wait=True)
    stats['selected_rows'] = len(selected)
    stats['with_skills'] = sum(bool(r['skills']) for r in selected)
    stats['salary_rows'] = sum(r['salary'] is not None for r in selected)
    stats['skill_histogram'] = dict(sorted(Counter(len(r['skills']) for r in selected).items()))
    stats['combinations'] = {
        str(k): {'distinct': sum(region == '' and len(stack) == k for region, stack in result),
                 'occurrences': sum(n for (region, stack), n in result.items()
                                    if region == '' and len(stack) == k)} for k in (1, 2, 3)}
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    values, regional = pay_statistics(selected, result)
    (out / 'counts.json').write_text(json.dumps(values, ensure_ascii=False, separators=(',', ':')))
    (out / 'regions.json').write_text(json.dumps(regional, ensure_ascii=False, separators=(',', ':')))
    (out / 'selected.json').write_text(json.dumps(selected, ensure_ascii=False, separators=(',', ':')))
    stats['seconds_inside'] = time.perf_counter() - begun
    (out / 'summary.json').write_text(json.dumps(stats, ensure_ascii=False, indent=2))
    print(json.dumps(stats, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--engine', choices=['baseline', 'combiner', 'fast', 'stream'], default='baseline')
    parser.add_argument('--chunk-rows', type=int, default=32768)
    parser.add_argument('--output-dir', default=str(ROOT / 'results' / 'mapreduce'))
    parser.add_argument('--inject-failure', action='store_true')
    run(parser.parse_args())
