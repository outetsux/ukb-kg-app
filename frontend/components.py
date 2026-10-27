import html
import json
import re
import textwrap
import pandas as pd
import streamlit as st
from streamlit.components.v1 import html as iframe
from pyvis.network import Network
from .client import api, release, ServiceError

COLORS = {'GENE':'#CC8B22','MEAS':'#B96354','DISO':'#A63F73','PHYS':'#665B9B','PROC':'#315A84',
          'CHEM':'#29808C','MISC':'#688F82','ANAT':'#AA8050','ACTI':'#7B8496','BASE':'#509DA0'}
from shared.entity_types import TYPE_NAMES


def theme():
    st.markdown('''<style>
    .block-container{max-width:1440px;padding-top:3rem;padding-bottom:3rem}
    h1,h2,h3{letter-spacing:-.025em} h1{font-weight:750!important}
    [data-testid="stMetric"]{background:white;border:1px solid #E1E8F0;border-radius:12px;padding:16px 20px}
    [data-testid="stSidebar"]{background:#EEF3F8;border-right:1px solid #DFE7EF}
    [data-testid="stVerticalBlockBorderWrapper"]{border-radius:12px}
    .eyebrow{font-size:.76rem;font-weight:700;letter-spacing:.13em;color:#147D92;margin-bottom:.55rem}
    .intro{font-size:1.08rem;line-height:1.7;color:#586B80;max-width:850px;margin-bottom:1.8rem}
    [data-testid="stMetricValue"]{font-size:1.75rem}
    button[aria-label="Download as CSV"]{display:none!important}
    [data-testid="stColumn"] h3{font-size:1.3rem;line-height:1.35;word-break:normal}
    @media(max-width:1100px){
      .block-container{padding-left:2rem;padding-right:2rem}
      [data-testid="stHorizontalBlock"]{flex-wrap:wrap}
      [data-testid="stHorizontalBlock"]>[data-testid="stColumn"]{min-width:190px;flex:1 1 190px}
    }
    @media(max-width:640px){
      .block-container{padding-left:1rem;padding-right:1rem}
      [data-testid="stHorizontalBlock"]>[data-testid="stColumn"]{min-width:100%;flex-basis:100%}
      h1{font-size:2rem!important}
    }
    </style>''', unsafe_allow_html=True)


def heading(title, description, eyebrow='UK BIOBANK KNOWLEDGE GRAPH'):
    st.markdown(f'<div class="eyebrow">{html.escape(eyebrow)}</div>', unsafe_allow_html=True)
    st.title(title)
    st.markdown(f'<div class="intro">{html.escape(description)}</div>', unsafe_allow_html=True)


def get_release():
    try:
        return release()
    except ServiceError as exc:
        st.error(str(exc))
        if st.button('Retry connection'):
            st.rerun()
        st.stop()


def metrics(stats):
    for col, label, value in zip(st.columns(3), ['Entities', 'Relationships', 'Entity types'],
                                [stats['nodes'], stats['relationships'], len(stats['entity_types'])]):
        col.metric(label, f'{value:,}')


def relationship_frame(edges):
    return pd.DataFrame([{'Entity':e['head'], 'Relationship':e['relation'], 'Related entity':e['tail'],
        'PMCID':e.get('pmcid') or 'Not available',
        'Paper':f"https://pmc.ncbi.nlm.nih.gov/articles/{e['pmcid']}/" if e.get('pmcid') else None,
        'Confidence score':e['confidence'], 'Frequency score':e['frequency'],
        'BIOS relation ID':e.get('bios_rid') or 'Not available',
        'Record ID':e['id']} for e in edges])


def graph_html(result, height=580, linear_path=False):
    edges, nodes = [], {}
    by_edge = {e['id']:e for e in result['edges']}
    by_node = {n['id']:n for n in result['nodes']}
    selected = set()
    groups = [p['edges'] for p in result['paths']] if result.get('paths') else [[e['id']] for e in result['edges']]
    for group in groups:
        incoming = [by_edge[e] for e in group if e not in selected]
        ids = {k for e in incoming for k in (e['source'],e['target'])}
        if len(selected) + len(incoming) > 500 or len(set(nodes) | ids) > 200:
            continue
        for e in incoming:
            selected.add(e['id']);edges.append(e)
        nodes.update({k:by_node[k] for k in ids})
    if not nodes:
        nodes = {n['id']:n for n in result['nodes'][:200]}
    net = Network(height=f'{height}px', width='100%', directed=True, bgcolor='#FFFFFF', font_color='#142D4E',
                  cdn_resources='in_line')
    positions={node:i for i,node in enumerate(result['paths'][0]['nodes'])} if linear_path and result.get('paths') else {}
    linear_path=bool(positions) and set(positions)==set(nodes)
    for n in nodes.values():
        label=textwrap.fill(n['name'],width=28) if linear_path else n['name']
        position={'x':positions[n['id']]*300,'y':0} if linear_path else {}
        # Canvas labels are plain text; PyVis serializes them with HTML-safe JSON.
        # Only HTML tooltips need entity escaping, otherwise apostrophes render as &#x27;.
        net.add_node(n['id'], label=label,
            title=html.escape(n['name'] + ' · ' + n['type']), color=COLORS.get(n['type'],'#7B8496'), size=18,**position)
    for e in edges:
        label=textwrap.fill(e['relation'],width=28) if linear_path else e['relation']
        net.add_edge(e['source'], e['target'], id=e['id'],
            title=html.escape(e['relation'] + ' · ' + (e.get('pmcid') or 'No PMCID')),
            label=label if len(edges) <= 35 else '', color='#B3C0CF', arrows='to')
    net.set_options(json.dumps({'layout':{'randomSeed':42},'physics': {'enabled':not linear_path,'solver':'barnesHut','stabilization':{'iterations':150}},
        'interaction':{'hover':True,'navigationButtons':True,'keyboard':True},
        'edges':{'smooth':False if linear_path else {'type':'dynamic'},'font':{'size':11}},'nodes':{'font':{'size':13}}}))
    # Freeze after initial layout, including graphs that never reach vis-network's velocity threshold.
    freeze = '''<script>
    (function () {
      let frozen = false;
      function freezeLayout() {
        if (frozen) return;
        frozen = true;
        network.stopSimulation();
        network.setOptions({physics: {enabled: false}});
      }
      network.once('stabilizationIterationsDone', freezeLayout);
      network.once('stabilized', freezeLayout);
      setTimeout(freezeLayout, 3000);
    })();
    </script>'''
    return net.generate_html().replace('</body>', freeze + '</body>'), len(edges) < len(result['edges'])


def show_paper(key, widget_key):
    try:
        data = api('papers/' + key)
    except ServiceError as exc:
        st.error(str(exc));return
    if not data['found']:
        st.info('No local metadata is available for this PMCID.');return
    p = data['paper']
    st.subheader(p.get('TI') or key)
    st.caption(' · '.join(str(v) for v in [p.get('JT'), p.get('DP'), key] if v))
    links = st.columns(3)
    links[0].link_button('Read on PMC', f'https://pmc.ncbi.nlm.nih.gov/articles/{key}/')
    if re.fullmatch(r'\d+', str(p.get('PMID') or '')):
        links[1].link_button('PubMed', f"https://pubmed.ncbi.nlm.nih.gov/{p['PMID']}/")
    doi = p.get('AID_doi')
    if isinstance(doi,str) and re.fullmatch(r'10\.\d{4,9}/\S+', doi):
        links[2].link_button('DOI', 'https://doi.org/' + doi)
    with st.expander('Abstract', expanded=True):
        st.write(p.get('AB') or 'Not available')
    with st.expander('Study population & baseline characteristics', expanded=True):
        baseline = data['baseline']
        if not baseline:
            st.write('Not available')
        else:
            records = baseline if isinstance(baseline,list) else [baseline]
            for i, record in enumerate(records):
                if len(records)>1:
                    st.markdown(f'**Study population {i+1}**')
                if isinstance(record,dict):
                    st.dataframe(pd.DataFrame([{'Characteristic':str(k).replace('_',' ').capitalize(),
                        'Value':json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else
                        ('Not available' if v is None or str(v).lower() in {'none','nan','','null'} else str(v))}
                        for k,v in record.items() if k.lower() not in {'pmc','pmcid'}]), hide_index=True, width='stretch')
                else:
                    st.write(record)
    with st.expander('Publication details'):
        st.dataframe(pd.DataFrame([{'Field':data['field_names'].get(k,k), 'Value':str(v or 'Not available')}
            for k,v in p.items() if k not in {'TI','AB','JIF','CT'}
            and data['field_names'].get(k,k).casefold() not in {'journal impact factor','citations'}]), hide_index=True, width='stretch')


def evidence_selector(edges, key):
    ids = sorted({e['pmcid'] for e in edges if e.get('pmcid')})
    if ids:
        selected = st.selectbox('Inspect paper context', ids, index=None, placeholder='Select a source paper', key=key)
        if selected:
            show_paper(selected, key + '_paper')
    else:
        st.caption('These relationships have no linked PMCID. External identifiers are shown where available.')


def show_graph(result, key, allow_export=False):
    if not result['nodes']:
        st.info('No matching relationships. Try broader filters or another entity.');return
    cols=st.columns(3)
    cols[0].metric('Returned entities',len(result['nodes']))
    cols[1].metric('Returned relationships',len(result['edges']))
    cols[2].metric('Paths' if 'path_count' in result else 'Total adjacent relationships',
                   result.get('path_count',result.get('total_relationships',len(result['edges']))))
    if result.get('truncated'):
        st.info('The result limit was reached.')
    gt,tt=st.tabs(['Graph','Relationships'])
    with gt:
        source,truncated=graph_html(result)
        iframe(source,height=600,scrolling=False)
        if truncated:
            st.caption('Graph preview is limited to 200 entities and 500 relationships. The table contains all returned records.')
        with st.expander('Entity type legend'):
            st.markdown(' · '.join(f'**{k}** — {v}' for k,v in TYPE_NAMES.items()))
    with tt:
        frame=relationship_frame(result['edges'])
        if not frame.empty:
            st.dataframe(frame,hide_index=True,width='stretch',column_config={'Paper':st.column_config.LinkColumn(display_text='PMC')})
            if allow_export:
                st.download_button('Download returned relationships',frame.to_csv(index=False).encode(),
                    file_name='ukb-kg-results.csv',mime='text/csv',key=key+'_download')
        else:
            st.info('This entity has no relationships.')
        st.caption('Scores are source and frequency indicators, not probabilities of correctness. Connections do not imply causation.')
    with st.expander('Source papers & contextual information'):
        evidence_selector(result['edges'],key+'_source')
