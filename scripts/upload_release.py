"""Verify and upload explicitly selected release artifacts to Modal, never source secrets."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared.release_files import DATA_FILES, MODEL_FILES, RELEASE_VERSION


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def verified_files(data_dir, model_dir):
    manifest_path = data_dir / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    if set(manifest['files']) != DATA_FILES or set(manifest.get('models', {})) != MODEL_FILES:
        raise ValueError('A complete data and model manifest is required.')
    if manifest.get('version') != RELEASE_VERSION:
        raise ValueError('Only the current release version can be uploaded.')
    if manifest.get('graph_schema_version') != 2:
        raise ValueError('Graph schema v2 is required.')
    files = [(manifest_path, '/data/manifest.json')]
    for folder, entries, prefix in [(data_dir, manifest['files'], '/data'),
                                     (model_dir, manifest['models'], '/models')]:
        for name, info in entries.items():
            relative = PurePosixPath(name)
            if relative.is_absolute() or '..' in relative.parts or '\\' in name:
                raise ValueError('Invalid manifest path.')
            source = folder / name
            if not source.resolve().is_relative_to(folder.resolve()) or source.is_symlink():
                raise ValueError('Release files must be regular files inside the selected directories.')
            if (not source.is_file() or source.stat().st_size != info['bytes']
                    or digest(source) != info['sha256']):
                raise ValueError('Release file is missing or does not match its checksum.')
            files.append((source, prefix + '/' + name))
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', required=True, type=Path)
    parser.add_argument('--model-dir', required=True, type=Path)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    files = verified_files(args.data_dir, args.model_dir)
    print(f'Verified {len(files)} release files.')
    if args.check_only:
        return
    import modal
    volume = modal.Volume.from_name('ukb-kg-release', create_if_missing=True)
    # Refuse accidental replacement of artifacts used by a live deployment.
    with volume.batch_upload(force=False) as upload:
        for source, target in files:
            upload.put_file(source, target)
    print('Release uploaded. Run the Modal import job before deploying the HTTP service.')


if __name__ == '__main__':
    main()
