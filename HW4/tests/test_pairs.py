import csv
import gzip
import io
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from pair_job import PairJob, batches


class PairTest(unittest.TestCase):
    def test_resume_from_checkpoint_keeps_prefix_once(self):
        buf = io.StringIO(newline='')
        writer = csv.writer(buf)
        writer.writerow(['source', 'vacancy_id', 'name', 'area', 'role', 'key_skills',
                         'currency', 'gross', 'salary_from', 'salary_to'])
        for number, title, skills, salary in [
            (1, 'Android разработчик', ' Android ; Kotlin ; android', 100000),
            (2, 'Android QA', 'Android; Kotlin', 200000),
            (3, 'Android разработчик', 'Kotlin; Android', 300000),
            (4, 'iOS разработчик', 'Swift; iOS', 200000),
        ]:
            writer.writerow(['hh', number, title, 'Москва', 'Программист, разработчик',
                             skills, 'RUR', 'false', salary, ''])
        data = gzip.compress(buf.getvalue().encode())
        job = PairJob()
        job.add(*next(batches(io.BytesIO(data), 2, 0)))
        resumed = PairJob.restore(job.snapshot('original'), 'original')
        for cursor, rows in batches(io.BytesIO(data), 2, resumed.input_rows):
            resumed.add(cursor, rows)
        self.assertEqual(resumed.input_rows, 4)
        self.assertEqual(resumed.selected_rows, 3)
        self.assertEqual(resumed.csv(), (
            'skill_1,skill_2,frequency,n_salary,median_salary\r\n'
            'android,kotlin,2,2,200000.0\r\n'
            'ios,swift,1,1,200000.0\r\n').encode())
        with self.assertRaises(ValueError):
            PairJob.restore(job.snapshot('original'), 'changed')
