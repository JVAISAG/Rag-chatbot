"""Evaluate generation from saved real retrieval ranks without loading CPU models."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
from src.generation.client import DEFAULT_MODEL, setting
from src.generation.llm import LLMGenerator
from src.workspace.library.questions import ANSWER_PROMPT_VERSION, answer_from_evidence
from src.workspace.library.answer_format import ANSWER_SYSTEM_PROMPT
from eval.workspace_dataset import load_dataset, dataset_fingerprint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', help='Override the local model for this run only.')
    parser.add_argument('--report', type=Path, default=ROOT / 'eval/workspace_answer_replay.json')
    parser.add_argument('--questions', help='Comma-separated question IDs for a diagnostic subset.')
    parser.add_argument('--dataset', type=Path, help='Evaluation corpus (default: the development set).')
    parser.add_argument('--retrieval-report', type=Path, help='Matching saved real retrieval ranks.')
    args = parser.parse_args()
    load_dotenv(ROOT / '.env', override=False)
    host = setting('OLLAMA_HOST', 'http://127.0.0.1:11434')
    if urlsplit(host if '://' in host else 'http://' + host).hostname not in {'localhost', '127.0.0.1', '::1'}:
        parser.error('Answer replay requires local Ollama.')
    try:
        dataset = load_dataset(args.dataset or ROOT / 'eval/workspace_set.json')
    except (OSError, ValueError, TypeError) as exc:
        parser.error(f'Invalid evaluation dataset: {type(exc).__name__}.')
    questions = dataset['questions']
    if args.questions is not None:
        identities = {item.strip() for item in args.questions.split(',') if item.strip()}
        if not identities or not identities.issubset({row['id'] for row in questions}):
            parser.error('Choose valid question IDs from the selected dataset.')
        questions = [row for row in questions if row['id'] in identities]
    try:
        retrieval = json.loads((args.retrieval_report or ROOT / 'eval/workspace_results.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        parser.error('Run verify_workspace.py evaluation --report eval/workspace_results.json first.')
    if not isinstance(retrieval, dict) or retrieval.get('dataset_sha256') != dataset_fingerprint(dataset):
        parser.error('Retrieval report does not match this dataset. Run its retrieval evaluation first.')
    sources = {source['id']: source for source in dataset['sources']}
    ranks = {}
    try:
        if retrieval.get('complete') is not True or not isinstance(retrieval['results'], list):
            raise ValueError('Incomplete retrieval report.')
        question_ids = {row['id'] for row in dataset['questions']}
        for row in retrieval['results']:
            if row['mode'] != 'reranked': continue
            if (row['question_id'] not in question_ids or row['question_id'] in ranks
                    or not isinstance(row['ranked_sources'], list)
                    or any(not isinstance(identity, str) or identity not in sources for identity in row['ranked_sources'])):
                raise ValueError('Invalid source ranks.')
            ranks[row['question_id']] = list(dict.fromkeys(row['ranked_sources']))
        if any(question['sources'] and question['id'] not in ranks for question in questions):
            raise ValueError('Missing source ranks.')
    except (KeyError, TypeError, ValueError):
        parser.error('Retrieval ranks are incomplete or contain unknown identities. Rerun retrieval evaluation.')
    model = args.model or setting('OLLAMA_MODEL', DEFAULT_MODEL)
    generator = LLMGenerator(model_name=model)
    report = {'complete': False, 'scope': dataset['scope'], 'dataset_sha256': dataset_fingerprint(dataset), 'model': model,
        'prompt_version': ANSWER_PROMPT_VERSION, 'context_tokens': generator.context_tokens,
        'system_prompt_sha256': hashlib.sha256(ANSWER_SYSTEM_PROMPT.encode('utf-8')).hexdigest(),
        'prompt_batch_size': int(setting('OLLAMA_BATCH_SIZE', '128')),
        'gpu_layers': setting('OLLAMA_GPU_LAYERS', 'auto'),
        'method': 'Generation-only replay of saved real reranked source order. Unanswerable questions start with the full corpus before context budgeting. Excludes retrieval, database, queue, and cold CPU-model loading.',
        'question_count': len(questions), 'corpus_question_count': len(dataset['questions']), 'answers': []}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    try:
        for question in questions:
            order = ranks.get(question['id'], list(sources))
            if question['sources'] and question['id'] not in ranks:
                raise RuntimeError('Missing saved retrieval result; rerun the retrieval benchmark first.')
            hits = [{'id': identity, 'text': sources[identity]['text'], 'metadata': {'source': identity + '.txt', 'source_id': identity}}
                for identity in order]
            _, selected = generator._prepare_context(question['question'], hits)
            started = perf_counter()
            answer, status = answer_from_evidence(generator, question['question'], selected, model)
            report['answers'].append({'question_id': question['id'], 'question': question['question'],
                'expected': question['answer'], 'answer': answer, 'status': status,
                'elapsed_seconds': round(perf_counter() - started, 4),
                'evidence': [{'number': number, 'source': item['id'], 'text': item['text']}
                    for number, item in enumerate(selected, 1)], 'requires_semantic_review': True})
            args.report.write_text(json.dumps(report, indent=2), encoding='utf-8')
            print(f"{question['id']}: {status}", flush=True)
        report['complete'] = True
        args.report.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(f'Saved generation-only replay: {args.report}', flush=True)
    finally:
        generator.client.close()


if __name__ == '__main__':
    main()
