"""UKB-KG/rag PARAMS=1/SCORE=1, manuscript Supplement C.3."""
K1, K2, K3 = 4, 50, 30
MAX_HOPS = 4
CONTEXT_TOKENS = 10000
CONFIDENCE_WEIGHT, FREQUENCY_WEIGHT, RELEVANCE_WEIGHT = .10, .05, .85


def retrieval_parameters():
    return {'reference':'UKB-KG/rag/retrieval.py','params':1,'score':1,
            'k1':K1,'k2':K2,'k3':K3,'max_hops':MAX_HOPS,'context_tokens':CONTEXT_TOKENS,
            'weights':{'confidence':CONFIDENCE_WEIGHT,'frequency':FREQUENCY_WEIGHT,'relevance':RELEVANCE_WEIGHT},
            'umls_alignment':False}
