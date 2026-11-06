from collections import Counter, defaultdict
import csv
import gzip
import io
from itertools import combinations
import json
from pathlib import Path
from statistics import median
import sys

HW3 = Path(__file__).resolve().parents[2] / 'HW3'
sys.path.insert(0, str(HW3 / 'scripts'))

from common import BUCKET, KEY, is_variant, python_rows, s3, selected_row
from mapreduce import map_batch


def batches(body, size, start):
    cursor = start
    batch = []
    for number, row in enumerate(python_rows(body), 1):
        if number <= start:
            continue
        cursor = number
        if is_variant(row):
            batch.append(selected_row(row))
        if (number - start) % size == 0:
            yield cursor, batch
            batch = []
    if (cursor - start) % size:
        yield cursor, batch


class PairJob:
    def __init__(self):
        self.input_rows = 0
        self.selected_rows = 0
        self.counts = Counter()
        self.salaries = defaultdict(list)

    def add(self, cursor, selected):
        if cursor <= self.input_rows:
            raise ValueError('Repeated chunk')
        for (region, stack), count in map_batch(selected, 'stream', False).items():
            if not region and len(stack) == 2:
                self.counts[stack] += count
        for row in selected:
            if row['salary'] is not None:
                for pair in combinations(row['skills'], 2):
                    self.salaries[pair].append(row['salary'])
        self.input_rows = cursor
        self.selected_rows += len(selected)

    def snapshot(self, etag):
        data = {
            'etag': etag,
            'input_rows': self.input_rows,
            'selected_rows': self.selected_rows,
            'pairs': [[*pair, n, self.salaries.get(pair, [])] for pair, n in self.counts.items()],
        }
        return gzip.compress(json.dumps(data, ensure_ascii=False).encode(), mtime=0)

    @classmethod
    def restore(cls, data, etag):
        state = json.loads(gzip.decompress(data))
        if state['etag'] != etag:
            raise ValueError('S3 object changed since checkpoint')
        job = cls()
        job.input_rows = state['input_rows']
        job.selected_rows = state['selected_rows']
        for a, b, n, salaries in state['pairs']:
            job.counts[(a, b)] = n
            if salaries:
                job.salaries[(a, b)] = salaries
        return job

    def csv(self):
        text = io.StringIO(newline='')
        writer = csv.writer(text)
        writer.writerow(['skill_1', 'skill_2', 'frequency', 'n_salary', 'median_salary'])
        for pair, n in sorted(self.counts.items(), key=lambda item: (-item[1], item[0])):
            salaries = self.salaries.get(pair, [])
            writer.writerow([*pair, n, len(salaries), median(salaries) if salaries else ''])
        return text.getvalue().encode()
