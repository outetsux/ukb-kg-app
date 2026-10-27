"""Deploy the service; release artifacts live exclusively in a private Volume."""
from pathlib import Path
import modal

ROOT = Path(__file__).resolve().parent
app = modal.App('ukb-kg-public')
volume = modal.Volume.from_name('ukb-kg-release')
image = (
    modal.Image.debian_slim(python_version='3.10')
    .pip_install('torch==2.6.0', index_url='https://download.pytorch.org/whl/cpu')
    .pip_install_from_requirements(str(ROOT / 'requirements-backend.txt'))
    .env({'UKB_DATA_DIR': '/release/data', 'UKB_MODEL_DIR': '/release/models',
          'TIKTOKEN_CACHE_DIR': '/opt/tiktoken', 'HF_HUB_OFFLINE': '1',
          'TRANSFORMERS_OFFLINE': '1', 'TOKENIZERS_PARALLELISM': 'false',
          'OMP_NUM_THREADS': '2', 'MKL_NUM_THREADS': '2',
          'UKB_RAG_ENABLED': 'true', 'UKB_EXPORT_ENABLED': 'false'})
    .run_commands('python -c "import tiktoken; tiktoken.get_encoding(\'o200k_base\')"')
    .add_local_dir(ROOT / 'backend', '/root/backend', ignore=['**/__pycache__/**', '**/*.pyc'])
    .add_local_dir(ROOT / 'shared', '/root/shared', ignore=['**/__pycache__/**', '**/*.pyc'])
    .add_local_file(ROOT / 'scripts/import_graph.py', '/root/scripts/import_graph.py')
)


@app.function(image=image, secrets=[modal.Secret.from_name('ukb-kg-service')],
              volumes={'/release': volume}, cpu=2, memory=8192,
              min_containers=0, max_containers=1, buffer_containers=0,
              scaledown_window=120, timeout=300)
@modal.concurrent(max_inputs=16)
@modal.asgi_app(requires_proxy_auth=True)
def web():
    from backend.app import app as api
    return api


@app.function(image=image, secrets=[modal.Secret.from_name('ukb-kg-import')],
              volumes={'/release': volume}, cpu=1, memory=4096,
              min_containers=0, max_containers=1, timeout=3600, retries=0)
def import_release():
    """Administrator-only RPC; never exposed as an HTTP route."""
    from scripts.import_graph import main
    main()


@app.local_entrypoint()
def main():
    import_release.remote()
