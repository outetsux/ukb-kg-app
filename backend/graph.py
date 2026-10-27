"""Parameterized queries against the typed-label publication database."""
from collections import defaultdict
import logging
import time
from neo4j import GraphDatabase, Query, READ_ACCESS
from neo4j.exceptions import ServiceUnavailable, SessionExpired
from .graph_schema import SCHEMA_VERSION, identifier
from shared.rag_settings import MAX_HOPS

log = logging.getLogger('ukb')


class GraphStore:
    def __init__(self, settings, catalog):
        self.catalog = catalog
        self.verified = False
        self.database = settings.neo4j_database
        self.driver = GraphDatabase.driver(settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password), connection_timeout=5,
            connection_acquisition_timeout=10, liveness_check_timeout=30,
            max_connection_lifetime=300,
            max_transaction_retry_time=0, max_connection_pool_size=4)

    def close(self):
        self.driver.close()

    def _read(self, query, deadline, **params):
        """Retry a failed read once in a new session, within the original budget."""
        for attempt in range(2):
            budget=deadline-time.monotonic()
            if budget<=0:
                raise TimeoutError('Graph query timed out.')
            try:
                with self.driver.session(database=self.database, default_access_mode=READ_ACCESS) as session:
                    return session.run(Query(query, timeout=budget), **params).data()
            except (ServiceUnavailable, SessionExpired) as exc:
                if attempt or time.monotonic()>=deadline:
                    raise
                # The driver discards defunct connections. A new session reacquires a live one.
                # Never log query text, names, credentials, or exception messages.
                log.warning('graph_read_retry type=%s',type(exc).__name__)

    def verify(self, timeout=15):
        self.verified = False
        rows = self._read('''MATCH (r:Release {owner:"ukb-kg-platform", status:"ready"})
                RETURN r.version AS version, r.relationships AS relationships, r.checksum AS checksum,
                       r.schema_version AS schema_version''',time.monotonic()+timeout)
        row=rows[0] if len(rows)==1 else None
        if not row or row['version'] != self.catalog.version or row['relationships'] != len(self.catalog.edges) or row['checksum'] != self.catalog.manifest['files']['triples_202603.csv']['sha256'] or row['schema_version'] != SCHEMA_VERSION:
            raise ValueError('Neo4j release/schema differs. Import the matching schema v2 release first.')
        self.verified = True

    def subgraph(self, spec, deadline=None):
        if not self.verified:
            raise RuntimeError('Graph release is not verified.')
        if spec.start_id not in self.catalog.nodes or (spec.end_id and spec.end_id not in self.catalog.nodes):
            raise ValueError('Select a valid entity.')
        start = self.catalog.nodes[spec.start_id]
        end = self.catalog.nodes[spec.end_id] if spec.end_id else None
        target = f"b:{identifier(end['type'])} {{name:$end}}" if end else 'b'
        query = f'''MATCH p=(a:{identifier(start['type'])} {{name:$start}})-[*HOPS]-({target})
        WHERE (size($types)=0 OR any(label IN labels(b) WHERE label IN $types))
          AND all(r IN relationships(p) WHERE r.row_id IS NOT NULL AND r.confidence >= $confidence
              AND (size($relations)=0 OR r.name IN $relations))
        RETURN [r IN relationships(p) | r.row_id] AS edges,
               [n IN nodes(p) | n.uid] AS nodes
        LIMIT $limit'''
        rows = []
        deadline = min(deadline or float("inf"), time.monotonic() + 15)
        for hops in range(1, spec.hops + 1):
            remaining = spec.limit + 1 - len(rows)
            if remaining <= 0:break
            rows.extend(self._read(query.replace('HOPS', str(hops)), deadline,
                start=start['name'], end=end['name'] if end else None, types=spec.target_types,
                confidence=spec.min_confidence, relations=spec.relationship_types, limit=remaining))
        truncated = len(rows) > spec.limit
        rows = rows[:spec.limit]
        graph = self.catalog.graph(e for p in rows for e in p['edges'])
        return {**graph, 'paths': rows, 'truncated': truncated, 'path_count': len(rows)}

    def shortest_paths(self, names, timeout=15):
        deadline=time.monotonic()+min(timeout,15)
        if not self.verified:
            # A transient startup outage must not disable paths until a process restart.
            self.verify(timeout=deadline-time.monotonic())
        names=list(dict.fromkeys(names))
        groups=defaultdict(list)
        order=0
        # Reference pairs distinct matched names, then its name lookup expands typed homonyms.
        # Do not add paths between two types of the same single matched name.
        for i,name in enumerate(names):
            for other in names[i+1:]:
                for aid in self.catalog.name_to_ids[name]:
                    for bid in self.catalog.name_to_ids[other]:
                        a,b=self.catalog.nodes[aid],self.catalog.nodes[bid]
                        groups[a['type'],b['type']].append({'a':name,'b':other,'order':order})
                        order+=1
        results=[]
        for (head_type,tail_type),pairs in groups.items():
            # Per-label name constraints provide indexed endpoint lookups.
            query=f'''UNWIND $pairs AS pair
                    MATCH (a:{identifier(head_type)} {{name:pair.a}}),
                          (b:{identifier(tail_type)} {{name:pair.b}}),
                          p=shortestPath((a)-[*..{MAX_HOPS}]-(b))
                    RETURN [r IN relationships(p) | r.row_id] AS edges,
                           [n IN nodes(p) | n.uid] AS nodes, pair.order AS pair_order'''
            results.extend(self._read(query, deadline, pairs=pairs))
        results.sort(key=lambda row:row['pair_order'])
        for row in results:row.pop('pair_order')
        return results
