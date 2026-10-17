from collections import defaultdict
from itertools import combinations
from statistics import median
from common import REGIONS


def pay_statistics(selected, counts):
    values = defaultdict(list)
    for row in selected:
        if row['salary'] is None:
            continue
        scopes = ('', row['area']) if row['area'] in REGIONS else ('',)
        for k in (1, 2, 3):
            for stack in combinations(row['skills'], k):
                for region in scopes:
                    values[(region, stack)].append(row['salary'])
    rows = []
    for (region, stack), n in sorted(counts.items()):
        salaries = values.get((region, stack), [])
        rows.append({'region': region, 'skills': list(stack), 'count': n,
                     'n_salary': len(salaries),
                     'median_salary': median(salaries) if salaries else None})
    regional = []
    for region in REGIONS:
        vacancies = [row for row in selected if row['area'] == region]
        salaries = [r['salary'] for r in vacancies if r['salary'] is not None]
        regional.append({'region': region, 'jobs': len(vacancies),
                         'with_skills': sum(bool(r['skills']) for r in vacancies),
                         'salary_jobs': len(salaries),
                         'median_salary': median(salaries) if salaries else None})
    return rows, regional
