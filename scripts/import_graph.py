"""Resumable typed-label import into a dedicated database. Never deletes data."""
from collections import defaultdict
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.config import settings
from backend.catalog import Catalog
from backend.graph_schema import SCHEMA_VERSION, identifier
from neo4j import GraphDatabase


def batches(items,size=500):
    for i in range(0,len(items),size):yield items[i:i+size]


def node_query(label):
    return f'''UNWIND $rows AS row
        MERGE (n:{identifier(label)} {{name:row.name}})
        SET n.uid=row.id, n.concept_id=row.concept_id'''


def relationship_query(head_type, tail_type, relation_type):
    return f'''UNWIND $rows AS row
        MATCH (a:{identifier(head_type)} {{name:row.head}}),
              (b:{identifier(tail_type)} {{name:row.tail}})
        MERGE (a)-[r:{identifier(relation_type)} {{row_id:row.id}}]->(b)
        SET r.name=row.relation, r.pmcid=row.pmcid, r.confidence=row.confidence,
            r.frequency=row.frequency, r.bios_rid=row.bios_rid'''


def import_catalog(session, catalog):
    if catalog.missing_scores:
        raise ValueError('Resolve missing source scores before importing. No database changes made.')
    checksum=catalog.manifest['files']['triples_202603.csv']['sha256']
    node_groups, edge_groups=defaultdict(list),defaultdict(list)
    for node in catalog.nodes.values():
        identifier(node['type'])
        node_groups[node['type']].append(node)
    for edge in catalog.edges.values():
        identifier(edge['relationship_type'])
        group=(catalog.nodes[edge['source']]['type'],catalog.nodes[edge['target']]['type'],edge['relationship_type'])
        edge_groups[group].append(edge)
    existing=session.run('MATCH (n) RETURN count(n) AS n').single()['n']
    release=session.run('MATCH (r:Release {owner:"ukb-kg-platform"}) RETURN r').single()
    if existing and (not release or release['r'].get('checksum')!=checksum
                     or release['r'].get('schema_version')!=SCHEMA_VERSION):
        raise ValueError('Database is nonempty and does not match this release/schema v2. Use a new dedicated instance; no data was changed.')
    for label in node_groups:
        session.run(f'CREATE CONSTRAINT {identifier(label+"_NAME")} IF NOT EXISTS FOR (n:{identifier(label)}) REQUIRE n.name IS UNIQUE').consume()
    session.run('CREATE CONSTRAINT release_owner IF NOT EXISTS FOR (n:Release) REQUIRE n.owner IS UNIQUE').consume()
    session.run('''MERGE (r:Release {owner:"ukb-kg-platform"})
        SET r.checksum=$checksum, r.schema_version=$schema, r.status="importing"''',
        checksum=checksum,schema=SCHEMA_VERSION).consume()
    for label,rows in node_groups.items():
        query=node_query(label)
        for batch in batches(rows):
            session.execute_write(lambda tx:tx.run(query,rows=batch).consume())
    print('Entities imported; importing typed relationships…',flush=True)
    for types,rows in edge_groups.items():
        query=relationship_query(*types)
        for batch in batches(rows):
            session.execute_write(lambda tx:tx.run(query,rows=batch).consume())
    actual_nodes={}
    for row in session.run('MATCH (n) WHERE NOT n:Release RETURN n.uid AS uid, n.name AS name, labels(n) AS labels'):
        if row['uid'] in actual_nodes:raise ValueError('Duplicate imported node identity.')
        actual_nodes[row['uid']]=(row['name'],tuple(sorted(row['labels'])))
    expected_nodes={n['id']:(n['name'],(n['type'],)) for n in catalog.nodes.values()}
    actual_edges={}
    for row in session.run('''MATCH (a)-[r]->(b) RETURN r.row_id AS id, a.uid AS source,
            b.uid AS target, type(r) AS type, r.name AS name, r.bios_rid AS bios_rid'''):
        if row['id'] in actual_edges:raise ValueError('Duplicate imported row_id.')
        actual_edges[row['id']]=(row['source'],row['target'],row['type'],row['name'],row['bios_rid'])
    expected_edges={e['id']:(e['source'],e['target'],e['relationship_type'],e['relation'],e['bios_rid']) for e in catalog.edges.values()}
    if actual_nodes!=expected_nodes or actual_edges!=expected_edges:
        raise ValueError('Post-import graph differs from release. Release remains unavailable.')
    session.run('''MATCH (r:Release {owner:"ukb-kg-platform"}) SET r.version=$version,
        r.nodes=$nodes, r.relationships=$edges, r.status="ready"''',
        version=catalog.version,nodes=len(actual_nodes),edges=len(actual_edges)).consume()
    print(f'Verified {len(actual_nodes):,} entities and {len(actual_edges):,} relationships (schema v{SCHEMA_VERSION}).')


def main():
    settings.validate(service=False)
    catalog=Catalog(settings.data_dir)
    with GraphDatabase.driver(settings.neo4j_uri,auth=(settings.neo4j_user,settings.neo4j_password)) as driver:
        with driver.session(database=settings.neo4j_database) as session:
            import_catalog(session,catalog)


if __name__=='__main__':main()
