"""Generate one current manifest from current files; no history is copied."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared.release_files import DATA_FILES, MODEL_FILES, RELEASE_VERSION
from shared.rag_settings import retrieval_parameters


def file_info(folder, name):
    path = folder / name
    if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(folder.resolve()):
        raise ValueError('Missing or unsafe release file: ' + name)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return {'sha256': digest.hexdigest(), 'bytes': path.stat().st_size}


def make_manifest(data_dir, model_dir):
    files = {name: file_info(data_dir, name) for name in sorted(DATA_FILES)}
    models = {name: file_info(model_dir, name) for name in sorted(MODEL_FILES)}
    nodes, row_ids = set(), set()
    required = {'row_id', 'HeadName', 'HeadType', 'HeadCID', 'TailName', 'TailType',
                'TailCID', 'RelName', 'RelType', 'RELID', 'PMCID',
                'Confidence_Score', 'Frequency_Score'}
    with (data_dir / 'triples_202603.csv').open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if not required <= set(reader.fieldnames or []):
            raise ValueError('The triples file is missing required columns.')
        for row in reader:
            if not row['row_id'] or row['row_id'] in row_ids:
                raise ValueError('Every relationship must have a unique, nonempty row_id.')
            row_ids.add(row['row_id'])
            for side in ('Head', 'Tail'):
                if not row[side + 'Name'] or not row[side + 'Type']:
                    raise ValueError('Entity names and types must be nonempty.')
                nodes.add((row[side + 'Type'], row[side + 'Name']))
            if not all(math.isfinite(float(row[key])) for key in ('Confidence_Score', 'Frequency_Score')):
                raise ValueError('Complete finite scores are required for retrieval.')
    if not row_ids:
        raise ValueError('The current release must not be empty.')
    return {'version': RELEASE_VERSION, 'graph_schema_version': 2,
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'nodes': len(nodes), 'relationships': len(row_ids),
            'files': files, 'models': models,
            'rag': {**retrieval_parameters(), 'entity_model': 'en_core_sci_scibert-0.5.4',
                    'encoder': 'biobert_v1.2', 'pooling': 'attention-mask mean'}}


def prepare(data_dir, model_dir):
    manifest = make_manifest(data_dir, model_dir)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', dir=data_dir, prefix='.manifest-', suffix='.tmp',
                                         encoding='utf-8', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(manifest, indent=2) + '\n')
        temporary.replace(data_dir / 'manifest.json')
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', required=True, type=Path)
    parser.add_argument('--model-dir', required=True, type=Path)
    args = parser.parse_args()
    manifest = prepare(args.data_dir, args.model_dir)
    print(f"Prepared release {manifest['version']}: {manifest['nodes']:,} entities / "
          f"{manifest['relationships']:,} relationships. Only current artifacts are listed.")


if __name__ == '__main__':
    main()
