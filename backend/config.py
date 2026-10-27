"""Cloud configuration. Credentials are injected by Modal Secrets."""
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
import os


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path(os.getenv('UKB_DATA_DIR', '/release/data'))
    model_dir: Path = Path(os.getenv('UKB_MODEL_DIR', '/release/models'))
    token: str = os.getenv('UKB_SERVICE_TOKEN', '')
    neo4j_uri: str = os.getenv('UKB_NEO4J_URI', '')
    neo4j_user: str = os.getenv('UKB_NEO4J_USER', 'neo4j')
    neo4j_password: str = os.getenv('UKB_NEO4J_PASSWORD', '')
    neo4j_database: str = os.getenv('UKB_NEO4J_DATABASE', 'neo4j')
    rag_enabled: bool = os.getenv('UKB_RAG_ENABLED', 'true').lower() == 'true'
    export_enabled: bool = os.getenv('UKB_EXPORT_ENABLED', 'false').lower() == 'true'

    def validate(self, *, service=True):
        uri = urlsplit(self.neo4j_uri)
        if (uri.scheme != 'neo4j+s' or not uri.hostname
                or not uri.hostname.endswith('.databases.neo4j.io')
                or uri.username or uri.password or uri.query or uri.fragment):
            raise RuntimeError('Configure an encrypted Neo4j Aura URI in Modal Secrets.')
        if not self.neo4j_password:
            raise RuntimeError('Configure the Neo4j password in Modal Secrets.')
        if service and (len(self.token) < 32 or self.token.startswith('REPLACE_')):
            raise RuntimeError('Configure UKB_SERVICE_TOKEN with a random token of at least 32 characters.')


settings = Settings()
