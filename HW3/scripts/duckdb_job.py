#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / ".packages"))

import duckdb


def sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def run(output_dir: Path) -> dict:
    output_dir = output_dir.resolve()
    if not output_dir.is_relative_to(PROJECT_ROOT):
        raise ValueError("The output directory must be inside the HW3 workspace")
    output_dir.mkdir(parents=True, exist_ok=True)

    extension_dir = PROJECT_ROOT / ".duckdb"
    temp_dir = PROJECT_ROOT / "tmp" / "duckdb"
    extension_dir.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)

    data_uri = os.environ.get(
        "HW3_DATA_URI", "s3://hh-lake/raw/it_vacancies_2024.csv.gz"
    )
    if not data_uri.startswith("s3://"):
        raise ValueError("HW3_DATA_URI must be an S3 URI")
    endpoint = os.environ.get("S3_ENDPOINT", "http://127.0.0.1:9100")
    parsed_endpoint = urlsplit(endpoint if "://" in endpoint else "http://" + endpoint)
    if parsed_endpoint.scheme not in {"http", "https"} or not parsed_endpoint.netloc:
        raise ValueError("S3_ENDPOINT must be an HTTP or HTTPS endpoint")
    if parsed_endpoint.path not in {"", "/"}:
        raise ValueError("The S3 endpoint must not contain a path")

    with duckdb.connect(
        database=":memory:",
        config={
            "extension_directory": str(extension_dir),
            "temp_directory": str(temp_dir),
            "memory_limit": "512MB",
            "threads": "2",
            "preserve_insertion_order": "false",
        },
    ) as connection:
        connection.execute("SET enable_progress_bar = false")
        try:
            connection.execute("LOAD httpfs")
        except duckdb.Error:
            connection.execute("INSTALL httpfs")
            connection.execute("LOAD httpfs")

        key = os.environ.get("AWS_ACCESS_KEY_ID", "hw3admin")
        secret = os.environ.get("AWS_SECRET_ACCESS_KEY", "hw3-local-secret")
        connection.execute(
            "CREATE SECRET hw3_s3 ("
            "TYPE S3, PROVIDER CONFIG, "
            f"KEY_ID {sql_string(key)}, SECRET {sql_string(secret)}, "
            f"ENDPOINT {sql_string(parsed_endpoint.netloc)}, "
            "REGION 'us-east-1', URL_STYLE 'path', "
            f"USE_SSL {'true' if parsed_endpoint.scheme == 'https' else 'false'}"
            ")"
        )
        connection.execute("SET VARIABLE data_uri = ?", [data_uri])
        connection.execute((PROJECT_ROOT / "sql" / "analysis.sql").read_text("utf-8"))

        exports = {
            "counts.json": (
                "SELECT region, skills, count, n_salary, median_salary "
                "FROM combination_counts ORDER BY region, len(skills), skills"
            ),
            "regions.json": (
                "SELECT region, jobs, with_skills, salary_jobs, median_salary "
                "FROM regional_summary ORDER BY sort_order"
            ),
            "selected.json": (
                "SELECT source, vacancy_id, name, area, skills, salary FROM selected "
                "ORDER BY source, vacancy_id, name, area, skills, salary"
            ),
        }
        for filename, query in exports.items():
            staging_path = output_dir / ("." + filename + ".tmp")
            connection.execute(
                f"COPY ({query}) TO {sql_string(str(staging_path))} "
                "(FORMAT JSON, ARRAY true)"
            )

        selected_rows, with_skills, salary_rows = connection.execute(
            "SELECT count(*), count(*) FILTER (WHERE len(skills) > 0), "
            "count(salary) FROM selected"
        ).fetchone()
        histogram = dict(
            connection.execute(
                "SELECT len(skills), count(*) FROM selected GROUP BY 1 ORDER BY 1"
            ).fetchall()
        )
        summary = {
            "input_rows": connection.execute(
                "SELECT input_rows FROM extraction"
            ).fetchone()[0],
            "selected_rows": selected_rows,
            "with_skills": with_skills,
            "salary_rows": salary_rows,
            "skill_histogram": histogram,
            "data_uri": data_uri,
        }
        (output_dir / ".summary.json.tmp").write_text(
            json.dumps(summary, ensure_ascii=False, sort_keys=True, allow_nan=False)
            + "\n",
            encoding="utf-8",
        )


        for filename in (*exports, "summary.json"):
            (output_dir / ("." + filename + ".tmp")).replace(output_dir / filename)
        return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir", type=Path, default=PROJECT_ROOT / "results" / "sql"
    )
    args = parser.parse_args()
    summary = run(args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
