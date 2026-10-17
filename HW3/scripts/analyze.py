from collections import Counter, defaultdict
import csv
from itertools import combinations
import json
from math import comb
from pathlib import Path
import statistics

from common import ROOT, REGIONS


def read(path):
    return json.loads(Path(path).read_text())


def count_dict(rows):
    return {(r['region'], tuple(r['skills'])): r['count'] for r in rows}


def row_dict(rows):
    return {(r['source'], r['vacancy_id']): r for r in rows}


def write_csv(path, names, rows):
    with Path(path).open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=names)
        writer.writeheader()
        writer.writerows(rows)


def verify():
    ledger = [json.loads(line) for line in (ROOT / 'evidence/profile.jsonl').read_text().splitlines()]
    base_dir = ROOT / next(r['output_dir'] for r in ledger
                           if r['mode'] == 'baseline' and not r['failure_injected'])
    base_rows = read(base_dir / 'counts.json')
    base_counts = count_dict(base_rows)
    base_pay = {(r['region'], tuple(r['skills'])): (r['n_salary'], r['median_salary'])
                for r in base_rows}
    base_selected = row_dict(read(base_dir / 'selected.json'))
    assert len(base_selected) == len(read(base_dir / 'selected.json')), 'Duplicate vacancy IDs'
    accepted = []
    for trial in ledger:
        folder = ROOT / trial['output_dir']
        entries = read(folder / 'counts.json')
        counts = count_dict(entries)
        pay = {(r['region'], tuple(r['skills'])): (r['n_salary'], r['median_salary'])
               for r in entries}
        rows = row_dict(read(folder / 'selected.json'))
        differences = sum(counts.get(k) != base_counts.get(k) for k in counts.keys() | base_counts.keys())
        assert differences == 0, (trial['mode'], trial['attempt'], differences)
        assert pay == base_pay, f'Salary counts or medians differ: {folder}'
        assert read(folder / 'regions.json') == read(base_dir / 'regions.json'), folder
        assert rows == base_selected, f'Selected data differ: {folder}'
        assert read(folder / 'summary.json')['input_rows'] == 229388
        accepted.append({'mode': trial['mode'], 'attempt': trial['attempt'],
                         'failure_injected': trial['failure_injected'],
                         'frequency_differences': 0, 'selected_differences': 0})
    for mode in ('baseline', 'combiner', 'fast', 'fast-2048', 'stream', 'duckdb'):
        assert len([r for r in accepted if r['mode'] == mode and not r['failure_injected']]) >= 3

    selected = list(base_selected.values())
    pay_values = defaultdict(list)
    for row in selected:
        if row['salary'] is None:
            continue
        regions = ('', row['area']) if row['area'] in REGIONS else ('',)
        for k in (1, 2, 3):
            for stack in combinations(row['skills'], k):
                for region in regions:
                    pay_values[(region, stack)].append(row['salary'])
    medians = {key: statistics.median(values) for key, values in pay_values.items()}
    sql_folder = ROOT / next(r['output_dir'] for r in ledger if r['mode'] == 'duckdb')
    sql_rows = read(sql_folder / 'counts.json')
    for row in sql_rows:
        key = (row['region'], tuple(row['skills']))
        assert row['n_salary'] == len(pay_values.get(key, [])), key
        assert row['median_salary'] == medians.get(key), key
    regional = []
    for region in REGIONS:
        rows = [r for r in selected if r['area'] == region]
        values = [r['salary'] for r in rows if r['salary'] is not None]
        regional.append({'region': region, 'jobs': len(rows),
                         'with_skills': sum(bool(r['skills']) for r in rows),
                         'salary_jobs': len(values),
                         'median_salary': statistics.median(values) if values else None})
    assert regional == read(sql_folder / 'regions.json'), 'Regional statistics differ'
    return ledger, accepted, base_counts, selected, pay_values, medians, regional


def main():
    ledger, accepted, counts, selected, pay_values, medians, regional = verify()
    out = ROOT / 'results'
    out.mkdir(exist_ok=True)
    controls = []
    top_stacks = []
    for k in (1, 2, 3):
        entries = sorted([(stack, n) for (region, stack), n in counts.items()
                          if region == '' and len(stack) == k], key=lambda v: (-v[1], v[0]))
        fields = [f'skill_{i}' for i in range(1, k + 1)] + ['frequency', 'n_salary', 'median_salary']
        values = []
        for stack, n in entries:
            item = {f'skill_{i}': s for i, s in enumerate(stack, 1)}
            item.update(frequency=n, n_salary=len(pay_values.get(('', stack), [])),
                        median_salary=medians.get(('', stack), ''))
            values.append(item)
        write_csv(out / f'skills_{k}.csv', fields, values)
        occurrences = sum(n for stack, n in entries)
        expected = sum(comb(len(row['skills']), k) for row in selected if len(row['skills']) >= k)
        assert occurrences == expected
        controls.append({'k': k, 'distinct': len(entries), 'occurrences': occurrences,
                         'sql_distinct': len(entries), 'sql_occurrences': occurrences,
                         'differences': 0})
        top_stacks.extend({'k': k, 'skills': list(stack), 'frequency': n}
                          for stack, n in entries[:5])

    lifts = []
    for (region, stack), n in counts.items():
        if region or len(stack) not in (2, 3) or len(pay_values.get(('', stack), [])) < 20:
            continue
        base = min(combinations(stack, len(stack) - 1), key=lambda s: (-counts[('', s)], s))
        base_median = medians[('', base)]
        median = medians[('', stack)]
        lifts.append({'k': len(stack), 'skills': list(stack), 'frequency': n,
                      'n_salary': len(pay_values[('', stack)]), 'base_skills': list(base),
                      'base_frequency': counts[('', base)], 'base_n_salary': len(pay_values[('', base)]),
                      'base_median': base_median, 'median': median,
                      'delta': median - base_median,
                      'delta_percent': (median / base_median - 1) * 100})
    salary_tables = {}
    for k in (2, 3):
        subset = [x for x in lifts if x['k'] == k]
        salary_tables[f'{k}_up'] = sorted([x for x in subset if x['delta'] > 0],
                                        key=lambda x: (-x['delta'], -x['n_salary'], x['skills']))[:3]
        salary_tables[f'{k}_down'] = sorted([x for x in subset if x['delta'] < 0],
                                          key=lambda x: (x['delta'], -x['n_salary'], x['skills']))[:3]
        assert salary_tables[f'{k}_up'] and salary_tables[f'{k}_down']
    fields = ['k', 'skills', 'frequency', 'n_salary', 'base_skills', 'base_frequency',
              'base_n_salary', 'base_median', 'median', 'delta', 'delta_percent']
    write_csv(out / 'salary_lift.csv', fields,
              [dict(row, skills='; '.join(row['skills']), base_skills='; '.join(row['base_skills']))
               for row in sorted(lifts, key=lambda x: (x['k'], -x['delta'], x['skills']))])
    write_csv(out / 'regions.csv', list(regional[0]), regional)
    regional_stacks = []
    for region in REGIONS:
        total = next(r['jobs'] for r in regional if r['region'] == region)
        for k in (1, 2, 3):
            stack, n = min(((stack, n) for (place, stack), n in counts.items()
                            if place == region and len(stack) == k), key=lambda x: (-x[1], x[0]))
            regional_stacks.append({'region': region, 'k': k, 'skills': list(stack),
                                    'frequency': n, 'share_percent': n / total * 100,
                                    'n_salary': len(pay_values.get((region, stack), [])),
                                    'median_salary': medians.get((region, stack))})
    write_csv(out / 'regional_skills.csv', list(regional_stacks[0]),
              [dict(row, skills='; '.join(row['skills'])) for row in regional_stacks])


    profiles = []
    for mode in ('baseline', 'combiner', 'fast', 'fast-2048', 'stream', 'duckdb'):
        trials = [r for r in ledger if r['mode'] == mode and not r['failure_injected']]
        profiles.append({'mode': mode, 'trials': trials,
                         'median_seconds': statistics.median(r['seconds'] for r in trials),
                         'median_peak_rss_mib': statistics.median(r['peak_rss_mib'] for r in trials),
                         'minimum_seconds': min(r['seconds'] for r in trials),
                         'maximum_seconds': max(r['seconds'] for r in trials)})
    baseline = profiles[0]

    feasible = [p for p in profiles[:-1]
                if p['median_peak_rss_mib'] <= baseline['median_peak_rss_mib']]
    winner = min(feasible, key=lambda x: x['median_seconds'])
    failure_trials = [r for r in ledger if r['failure_injected']]
    assert failure_trials, 'The real mapper failure test has not run'
    failure = read(ROOT / failure_trials[-1]['output_dir'] / 'summary.json')
    assert failure['retries'] == 1 and failure['mapper_exit_code'] == 23
    result = {'variant': 9, 'student': 'Муртазалиев Матвей Асланович',
              'input_rows': 229388, 'selected_rows': len(selected),
              'with_skills': sum(bool(r['skills']) for r in selected),
              'salary_rows': sum(r['salary'] is not None for r in selected),
              'controls': controls, 'top_stacks': top_stacks,
              'salary_tables': salary_tables, 'salary_eligible_combinations': len(lifts),
              'regions': regional, 'regional_stacks': regional_stacks, 'profiles': profiles,
              'winner': winner['mode'], 'speedup': baseline['median_seconds'] / winner['median_seconds'],
              'memory_reduction_percent': (1 - winner['median_peak_rss_mib'] /
                                            baseline['median_peak_rss_mib']) * 100,
              'mapper_failure': failure,
              'verified_runs': len(accepted), 'differences': 0,
              'salary_medians_verified': len(counts)}
    (out / 'analysis.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    (out / 'verification.json').write_text(json.dumps(accepted, ensure_ascii=False, indent=2))
    print(f'variant=9; input_rows=229388; selected_rows={len(selected)}')
    print(f'with_skills={result["with_skills"]}; salary_rows={result["salary_rows"]}')
    print(f'MapReduce vs DuckDB: groups={len(counts)}; differences=0')
    for row in controls:
        print(f'k={row["k"]}; distinct={row["distinct"]}; occurrences={row["occurrences"]}; differences=0')
    print(f'salary_medians_checked={len(counts)}; differences=0')
    print(f'mapper_exit=23; retries=1; frequency_differences=0')
    print(f'verified_runs={len(accepted)}; winner={winner["mode"]}; speedup={result["speedup"]:.3f}')


if __name__ == '__main__':
    main()
