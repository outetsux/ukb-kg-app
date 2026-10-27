"""One release, deterministic IDs, and no inferred paper provenance."""
from collections import Counter, defaultdict
from pathlib import Path
import csv
import hashlib
import json
import re
import math

from shared.entity_types import TYPE_NAMES


def node_id(name, entity_type):
    return hashlib.sha256(json.dumps([entity_type, name], ensure_ascii=False).encode()).hexdigest()[:24]


def pmcid(value):
    value = str(value or '').strip().upper()
    if value.isdigit():
        value = 'PMC' + value
    return value if re.fullmatch(r'PMC\d+', value) else None


def clean(value):
    if value is None or str(value).strip().lower() in {'', 'none', 'nan', 'null', 'n/a'}:
        return None
    return value


class Catalog:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.manifest = json.loads((data_dir / 'manifest.json').read_text())
        self.version = self.manifest['version']
        # Enforce the declared release before reading trusted local artifacts.
        for name, info in self.manifest['files'].items():
            path = data_dir / name
            digest = hashlib.sha256()
            if path.exists():
                with path.open('rb') as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(block)
            if not path.exists() or digest.hexdigest() != info['sha256']:
                raise ValueError(f'Release file checksum mismatch: {name}')
        self.nodes, self.edges, self.adjacency = {}, {}, defaultdict(list)
        self.head_index, self.tail_index = defaultdict(list), defaultdict(list)
        self.name_to_ids = defaultdict(list)
        with (data_dir / 'triples_202603.csv').open(newline='', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                for side in ('Head', 'Tail'):
                    name = row[side + 'Name']
                    key = node_id(name, row[side + 'Type'])
                    if key not in self.name_to_ids[name]:
                        self.name_to_ids[name].append(key)
                    self.nodes.setdefault(key, {'id': key, 'name': name, 'type': row[side + 'Type'],
                                                'concept_id': clean(row[side + 'CID'])})
                key = row['row_id']
                if key in self.edges:
                    raise ValueError('Duplicate row_id in release.')
                edge = {'id': key, 'source': node_id(row['HeadName'], row['HeadType']), 'target': node_id(row['TailName'], row['TailType']),
                        'head': row['HeadName'], 'relation': row['RelName'], 'tail': row['TailName'],
                        'relationship_type': row['RelType'],
                        'pmcid': pmcid(row['PMCID']), 'bios_rid': clean(row['RELID']),
                        'confidence': float(row['Confidence_Score']) if clean(row['Confidence_Score']) else None,
                        'frequency': float(row['Frequency_Score']) if clean(row['Frequency_Score']) else None}
                if not all(edge[k] is None or math.isfinite(edge[k]) for k in ('confidence','frequency')):
                    raise ValueError('Scores must be finite numbers.')
                self.edges[key] = edge
                self.adjacency[edge['source']].append(key)
                if edge['target'] != edge['source']:
                    self.adjacency[edge['target']].append(key)
                self.head_index[edge['head']].append(key)
                self.tail_index[edge['tail']].append(key)
        if len(self.nodes) != self.manifest['nodes'] or len(self.edges) != self.manifest['relationships']:
            raise ValueError('Release counts do not match manifest.')
        self.names = list(self.name_to_ids)
        self.missing_scores = sum(any(e[k] is None for k in ('confidence','frequency')) for e in self.edges.values())
        self.stats = self._statistics()

    def _statistics(self):
        counts = Counter(n['type'] for n in self.nodes.values())
        degrees, matrix = Counter(), Counter()
        for edge in self.edges.values():
            a, b = self.nodes[edge['source']]['type'], self.nodes[edge['target']]['type']
            degrees[a] += 1
            degrees[b] += 1
            matrix[a, b] += 1
        return {'nodes': len(self.nodes), 'relationships': len(self.edges),
                'entity_types': [{'type': k, 'name': TYPE_NAMES.get(k, k), 'count': v,
                                  'average_degree': degrees[k] / v} for k, v in counts.most_common()],
                'connections': [{'source': a, 'target': b, 'count': v} for (a, b), v in matrix.items()],
                'with_pmcid': sum(bool(e['pmcid']) for e in self.edges.values()),
                'without_pmcid': sum(not e['pmcid'] for e in self.edges.values()),
                'relation_types': sorted({e['relation'] for e in self.edges.values()})}

    def search(self, query, limit=30):
        from rapidfuzz import process, fuzz
        query = query.strip().casefold()
        if not query:
            return {'nodes': [], 'suggestions': False}
        matches = [n for n in self.nodes.values() if query in n['name'].casefold()]
        matches.sort(key=lambda n: (0 if n['name'].casefold() == query else
                                    1 if n['name'].casefold().startswith(query) else 2,
                                    -len(self.adjacency[n['id']]), n['name']))
        suggestions = not matches
        if suggestions:
            names = process.extract(query, self.names, scorer=fuzz.WRatio, processor=str.casefold,
                                    limit=10, score_cutoff=55)
            matches = [self.nodes[key] for name, _, _ in names for key in self.name_to_ids[name]]
        return {'nodes': matches[:limit], 'suggestions': suggestions}

    def neighborhood(self, key, limit=200):
        if key not in self.nodes:
            raise KeyError('Unknown entity.')
        ids = sorted(self.adjacency[key], key=lambda eid: -len(self.adjacency[
            self.edges[eid]['target'] if self.edges[eid]['source'] == key else self.edges[eid]['source']]))
        result = self.graph(ids[:limit])
        if not result['nodes']:
            result['nodes'] = [self.nodes[key]]
        result.update(truncated=len(ids) > limit, total_relationships=len(ids))
        return result

    def graph(self, edge_ids):
        edges = [self.edges[k] for k in dict.fromkeys(edge_ids)]
        keys = dict.fromkeys(k for e in edges for k in (e['source'], e['target']))
        return {'nodes': [self.nodes[k] for k in keys], 'edges': edges}

    def candidates(self, names):
        # Preserve original head-then-tail order and duplicate occurrences across matched entities.
        return [self.edges[k] for name in names for index in (self.head_index, self.tail_index)
                for k in index.get(name, [])]
