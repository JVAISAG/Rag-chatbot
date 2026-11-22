"""Validate benchmark inputs and bind reports to the exact corpus contents."""
import hashlib
import json
from pathlib import Path
import re


def load_dataset(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    identity = re.compile(r'[a-z][a-z0-9-]{0,63}')
    if not isinstance(data, dict) or not isinstance(data.get('scope'), str) or not data['scope'].strip():
        raise ValueError('A dataset must declare its evaluation scope.')
    data['scope'].encode('utf-8')
    sources, questions = data.get('sources'), data.get('questions')
    if not isinstance(sources, list) or not sources or not isinstance(questions, list) or not questions:
        raise ValueError('A dataset needs sources and questions.')
    ids, question_ids = set(), set()
    def valid_text(value, limit):
        return isinstance(value, str) and bool(value.strip()) and len(value) <= limit and '\x00' not in value
    for source in sources:
        if (not isinstance(source, dict) or not isinstance(source.get('id'), str) or not identity.fullmatch(source['id'])
                or source['id'] in ids or source.get('kind') not in {'paper', 'article'}
                or not valid_text(source.get('text'), 100000)):
            raise ValueError('Invalid or duplicate evaluation source.')
        source['text'].encode('utf-8')
        ids.add(source['id'])
    for question in questions:
        if (not isinstance(question, dict) or not isinstance(question.get('id'), str) or not identity.fullmatch(question['id'])
                or question['id'] in question_ids or not valid_text(question.get('question'), 2000)
                or not isinstance(question.get('sources'), list) or any(not isinstance(value, str) for value in question['sources'])
                or len(question['sources']) != len(set(question['sources'])) or not set(question['sources']).issubset(ids)
                or (not question['sources'] and question.get('answer') is not None)
                or (question['sources'] and not valid_text(question.get('answer'), 4000))):
            raise ValueError('Invalid, duplicate, or ungrounded evaluation question.')
        question['question'].encode('utf-8')
        if question.get('answer') is not None:
            question['answer'].encode('utf-8')
        question_ids.add(question['id'])
    return data


def dataset_fingerprint(dataset):
    canonical = json.dumps(dataset, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(canonical).hexdigest()
