from pathlib import Path
import csv
import gzip
import io
import math
import os
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if (ROOT / '.packages').exists():
    sys.path.insert(0, str(ROOT / '.packages'))

ROLE = 'Программист, разработчик'
PATTERN = (r'(?:^|[^a-zа-яё0-9_])(?:android|андроид|ios|iphone|ipad|flutter|dart|'
           r'react[ -]*native|xamarin|swift|objective[ -]*c|mobile|мобильн[а-яё]*)'
           r'(?:[^a-zа-яё0-9_]|$)')
MOBILE = re.compile(PATTERN)
EXCLUDE_PATTERN = (
    r'(?:^|[^a-zа-яё0-9_])(?:qa|aqa|sdet|tester|testing|test|quality|'
    r'тестиров[а-яё]*|тестирован[а-яё]*|автотест[а-яё]*|project|product|'
    r'менеджер[а-яё]*|manager|консультант[а-яё]*|преподавател[а-яё]*|'
    r'художник[а-яё]*|artist|backend|back[ -]*end|б[эе]к[эе]нд[а-яё]*|'
    r'серверн[а-яё]*|sre|devops)(?:[^a-zа-яё0-9_]|$)|'
    r'мобильн[а-яё]*[ -]+(?:оператор[а-яё]*|сет[а-яё]*|торговл[а-яё]*)|'
    r'mobile[ -]+web|мобильн[а-яё]*[ -]+верси[а-яё]*|release[ -]+train|'
    r'автор[ -]+работ|руководитель[ -]+направлени|head[ -]+of[ -]+mobile|'
    r'техническ[а-яё]*[ -]+специалист[а-яё]*|специалист[а-яё]*[ -]+поддержк[а-яё]*'
)
EXCLUDED_TITLE = re.compile(EXCLUDE_PATTERN)
NATIVE_PATTERN = (r'(?:^|[^a-zа-яё0-9_])(?:android|андроид|ios|iphone|ipad|flutter|'
                  r'react[ .-]*native|xamarin|swift|objective[ -]*c|'
                  r'kotlin[ -]*multiplatform|kmp|kmm|qt|qml|maui|ionic|'
                  r'kivy|cordova|phonegap|nativescript|unity|capacitor|jetpack[ -]+compose|'
                  r'compose[ -]+multiplatform|мобильн[а-яё]*[ -]+интерфейс[а-яё]*[ -]+на[ -]+compose|'
                  r'unreal[ -]*engine|mobile[ -]*smarts|datamobile)(?:[^a-zа-яё0-9_]|$)|'
                  r'1[сc].{0,60}мобильн|мобильн.{0,60}1[сc]')
NATIVE = re.compile(NATIVE_PATTERN)
CLIENT_DESCRIPTION_PATTERN = (r'(?:^|[^a-zа-яё0-9_])(?:flutter|react[ .-]*native|xamarin|swift|'
                              r'objective[ -]*c|kotlin[ -]*multiplatform|kmp|kmm|qt|qml|maui|ionic|'
                              r'kivy|cordova|phonegap|nativescript|unity|capacitor|jetpack[ -]+compose|'
                              r'compose[ -]+multiplatform|мобильн[а-яё]*[ -]+интерфейс[а-яё]*[ -]+на[ -]+compose|'
                              r'unreal[ -]*engine|mobile[ -]*smarts|datamobile)(?:[^a-zа-яё0-9_]|$)|'
                              r'1[сc].{0,60}мобильн|мобильн.{0,60}1[сc]')
CLIENT_DESCRIPTION = re.compile(CLIENT_DESCRIPTION_PATTERN)
SERVER_TITLE_PATTERN = r'(?:^|[^a-zа-яё0-9_])(?:python|php|golang|go|java)(?:[^a-zа-яё0-9_]|$)'
WEB_TITLE = re.compile(r'(?:^|[^a-zа-яё0-9_])(?:web|веб|front[ -]*end|фронт[эе]нд[а-яё]*)(?:[^a-zа-яё0-9_]|$)')
MOBILE_PUBLISH = re.compile(r'(?:размещени|публикаци)[а-яё]*.{0,100}мобильн[а-яё]*.{0,60}(?:магазин|приложени)')
SERVER_SKILLS_PATTERN = (r'(?:^|[^a-zа-яё0-9_])(?:spring[ a-z]*|django|flask|fastapi|'
                        r'laravel|symfony|nest[ .]?js|node[ .]?js|asp[ .]?net|'
                        r'php|golang|hibernate|jdbc|backend|back[ -]*end|'
                        r'б[эе]к[эе]нд[а-яё]*)(?:[^a-zа-яё0-9_]|$)')
SERVER_TITLE = re.compile(SERVER_TITLE_PATTERN)
SERVER_SKILLS = re.compile(SERVER_SKILLS_PATTERN)
REGIONS = ('Москва', 'Санкт-Петербург', 'Новосибирск')
FIELDS = ['source', 'vacancy_id', 'name', 'role', 'area', 'salary_from', 'salary_to',
          'currency', 'gross', 'key_skills', 'description']
BUCKET = 'hh-lake'
KEY = 'raw/it_vacancies_2024.csv.gz'
DATA_URI = f's3://{BUCKET}/{KEY}'
ENDPOINT = os.environ.get('S3_ENDPOINT', 'http://127.0.0.1:9100')
ACCESS_KEY = os.environ.get('AWS_ACCESS_KEY_ID', 'hw3admin')
SECRET_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY', 'hw3-local-secret')


def s3():
    import boto3
    from botocore.config import Config
    return boto3.client('s3', endpoint_url=ENDPOINT,
                        aws_access_key_id=ACCESS_KEY, aws_secret_access_key=SECRET_KEY,
                        region_name='us-east-1',
                        config=Config(signature_version='s3v4',
                                      s3={'addressing_style': 'path'},
                                      request_checksum_calculation='when_required',
                                      response_checksum_validation='when_required',
                                      retries={'max_attempts': 3, 'mode': 'standard'}))


def is_variant(row):
    title = row.get('name', '').lower()
    if row.get('role') != ROLE or not MOBILE.search(title) or EXCLUDED_TITLE.search(title):
        return False
    skill_text = row.get('key_skills', '').lower()
    description = row.get('description', '').lower()
    if NATIVE.search(title) or NATIVE.search(skill_text):
        return True



    if (SERVER_TITLE.search(title) or SERVER_SKILLS.search(skill_text)) and not CLIENT_DESCRIPTION.search(description):
        return False
    if WEB_TITLE.search(title) and not CLIENT_DESCRIPTION.search(description):
        return False
    if SERVER_SKILLS.search(description) and not (
            CLIENT_DESCRIPTION.search(description) or MOBILE_PUBLISH.search(description)):
        return False
    return True


def skills(value):
    return tuple(sorted({re.sub(r'[ \t\r\n\f\v]+', ' ', s.strip()).lower()
                         for s in (value or '').split(';') if s.strip()}))


def salary(row):
    if row.get('currency', '').strip().upper() not in ('RUR', 'RUB'):
        return None
    if row.get('gross', '').strip().lower() != 'false':
        return None
    positive = []
    for key in ('salary_from', 'salary_to'):
        try:
            number = float(row.get(key, ''))
        except (ValueError, TypeError):
            continue
        if math.isfinite(number) and number > 0:
            positive.append(number)
    return sum(positive) / len(positive) if positive else None


def selected_row(row):
    return {'source': row['source'], 'vacancy_id': row['vacancy_id'], 'name': row['name'],
            'area': row['area'], 'skills': list(skills(row.get('key_skills', ''))),
            'salary': salary(row)}


def python_rows(body):
    csv.field_size_limit(16 * 1024 * 1024)
    with gzip.GzipFile(fileobj=body, mode='rb') as packed:
        with io.TextIOWrapper(packed, encoding='utf-8-sig', newline='') as stream:
            yield from csv.DictReader(stream)
