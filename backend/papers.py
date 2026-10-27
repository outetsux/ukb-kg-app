import csv
import json
from .catalog import clean, pmcid

FIELD_NAMES = {'TI':'Title', 'AB':'Abstract', 'FAU':'Authors', 'AU':'Authors', 'JT':'Journal',
    'TA':'Journal abbreviation', 'DP':'Publication date', 'PMID':'PMID', 'PMC':'PMCID',
    'AD':'Affiliations', 'AID':'Article identifiers', 'PT':'Publication type', 'MH':'MeSH terms',
    'KW':'Keywords', 'CT':'Citations', 'JIF':'Journal impact factor', 'UKB':'Uses UKB data',
    'LA':'Language', 'URL':'Article URL', 'VI':'Volume', 'IP':'Issue', 'IS':'ISSN',
    'AUID':'Author identifiers', 'GR':'Grants', 'SO':'Source'}


class PaperStore:
    def __init__(self, folder):
        # Consortium author/affiliation lists can exceed Python's default 128 KiB CSV field limit.
        csv.field_size_limit(10 * 1024 * 1024)
        self.papers, self.baselines = {}, {}
        path = folder / 'pubmed-ukb_202603.csv'
        if path.exists():
            with path.open(encoding='utf-8-sig', newline='') as f:
                for row in csv.DictReader(f):
                    key = pmcid(row.get('PMC') or row.get('PMCID'))
                    if key:
                        self.papers[key] = {k: clean(v) for k, v in row.items() if k and not k.startswith('Unnamed')}
        path = folder / 'baseline_202603.json'
        if path.exists():
            data = json.loads(path.read_text())
            if isinstance(data, dict):
                for key, value in data.items():
                    normalized = pmcid(key)
                    if normalized:
                        self.baselines[normalized] = value
            elif isinstance(data, list):
                for value in data:
                    if isinstance(value, dict):
                        key = pmcid(value.get('PMCID') or value.get('PMC') or value.get('pmcid'))
                        if key:
                            self.baselines[key] = value
                        else:
                            for filename, cohorts in value.items():
                                key = pmcid(filename.removesuffix('.xml'))
                                if key:
                                    self.baselines.setdefault(key, []).extend(cohorts if isinstance(cohorts, list) else [cohorts])

    def get(self, key):
        key = pmcid(key)
        if not key:
            raise ValueError('Enter a valid PMCID, for example PMC8416852.')
        paper = self.papers.get(key, {})
        baseline = self.baselines.get(key)
        return {'pmcid': key, 'found': bool(paper or baseline), 'paper': paper,
                'baseline': baseline, 'field_names': FIELD_NAMES}
