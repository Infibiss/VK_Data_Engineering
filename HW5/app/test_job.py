import csv
import gzip
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import job
from aggregates import pay_statistics
from common import FIELDS, is_variant, selected_row


class PipelineTest(unittest.TestCase):
    def test_single_and_four_shards_match_hw3(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'input.csv.gz'
            rows = []
            for i, amount in enumerate((100, 110, 200, 350, 1000, 2000, 3000)):
                row = dict.fromkeys(FIELDS, '')
                row.update(source='fixture', vacancy_id=str(i), name='Android developer',
                           role='Программист, разработчик', area='Москва', currency='RUR',
                           gross='false', salary_from=str(amount),
                           key_skills='Kotlin; Android; kotlin; Git',
                           description='Native apps, quoted text\nwith newline')
                rows.append(row)
            rows[1]['gross'] = 'true'
            rows[2]['currency'] = 'USD'
            rows[3]['name'] = 'QA Android tester'
            rows[4]['key_skills'] = ' Kotlin ; Android '
            rows[5]['key_skills'] = ''
            with gzip.open(source, 'wt', encoding='utf-8', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(rows)

            def invoke(*arguments):
                subprocess.run([sys.executable, str(Path(job.__file__)), *map(str, arguments)],
                               check=True, stdout=subprocess.PIPE, text=True)

            invoke('single', '--input', source, '--output-prefix', root / 'single', '--chunk-rows', 2)
            invoke('split', '--input', source, '--shards', 4, '--shard-prefix', root / 'shards')
            for index in range(4):
                invoke('worker', '--shard-prefix', root / 'shards', '--shards', 4,
                       '--index', index, '--output-prefix', root / 'parts', '--chunk-rows', 2)
            invoke('reduce', '--parts-prefix', root / 'parts', '--shards', 4,
                   '--output-prefix', root / 'reduced')
            selected = [selected_row(row) for row in rows if is_variant(row)]
            counts = job.map_batch(selected, 'combiner', False)
            aggregates, _ = pay_statistics(selected, counts)
            expected = []
            for row in sorted((r for r in aggregates if not r['region'] and len(r['skills']) == 2),
                              key=lambda r: (-r['count'], r['skills'])):
                expected.append({'skill_1': row['skills'][0], 'skill_2': row['skills'][1],
                                 'frequency': row['count'], 'n_salary': row['n_salary'],
                                 'median_salary': row['median_salary'] if row['median_salary'] is not None else ''})
            for mode in ('single', 'reduced'):
                self.assertEqual((root / mode / 'skills_2.csv').read_bytes(), job.csv_data(expected))
                self.assertEqual((root / mode / 'top10.csv').read_bytes(), job.csv_data(expected[:10]))
                stats = json.loads((root / mode / 'summary.json').read_text())
                self.assertEqual(stats['input_rows'], len(rows))
                self.assertEqual(stats['selected_rows'], len(selected))
                self.assertGreater(stats['peak_rss_mib'], 0)
            self.assertEqual(json.loads((root / 'shards/manifest.json').read_text())['rows_per_shard'],
                             [2, 2, 2, 1])


if __name__ == '__main__':
    unittest.main()
