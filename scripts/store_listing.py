"""Prepare Korean-first listing text offline; preserve all nontext submission data."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re

CONFIG = Path(__file__).resolve().parents[1]/'config/store-listing-ko.json'
MAX_CONFIG = 64*1024
TEXT_FIELDS = frozenset({'description','features','releaseNotes'})


def _korean(value, limit):
    return (isinstance(value,str) and 0 < len(value) <= limit and value.strip()
            and re.search(r'[가-힣]',value.split('\n',1)[0]) is not None)


def _validate(text):
    if (not isinstance(text,dict) or set(text) != TEXT_FIELDS
            or not _korean(text.get('description'),10000)
            or not _korean(text.get('releaseNotes'),1500)
            or not isinstance(text.get('features'),list) or not 1 <= len(text['features']) <= 20
            or any(not _korean(value,200) for value in text['features'])):
        raise ValueError('검토된 한국어 설명·기능·변경 사항만 Store 설명에 적용할 수 있습니다.')
    return text


def _pairs(items):
    value={}
    for key,item in items:
        if key in value:raise ValueError('Store 설명 설정에 중복 항목이 있습니다.')
        value[key]=item
    return value


def load_listing(path=None):
    path=CONFIG if path is None else Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('검토된 Store 설명 설정 파일이 필요합니다.')
    with path.open('rb') as stream:data=stream.read(MAX_CONFIG+1)
    if not 0 < len(data) <= MAX_CONFIG:
        raise ValueError('Store 설명 설정 파일이 크기 제한을 초과했습니다.')
    try:text=json.loads(data.decode('utf-8'),object_pairs_hook=_pairs)
    except (UnicodeError,json.JSONDecodeError):
        raise ValueError('Store 설명 설정을 읽을 수 없습니다.') from None
    return _validate(text)


def apply_korean_listing(submission, text=None):
    """Return a copy; only three baseListing text fields may change in existing locales."""
    text=load_listing() if text is None else _validate(text)
    listings=submission.get('listings') if isinstance(submission,dict) else None
    if (not isinstance(listings,dict) or 'ko-kr' not in listings
            or any(not isinstance(locale,str) or not locale
                   or not isinstance(value,dict) or not isinstance(value.get('baseListing'),dict)
                   for locale,value in listings.items())):
        raise ValueError('기존 한국어 목록과 모든 언어의 Store 기본 설명이 필요합니다.')
    result=copy.deepcopy(submission)
    for value in result['listings'].values():
        value['baseListing'].update(copy.deepcopy(text))
    return result
