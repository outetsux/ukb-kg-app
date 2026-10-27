import streamlit as st
from frontend.client import api,ServiceError
from frontend.components import heading,get_release,show_graph,show_paper,TYPE_NAMES

heading('Basic Search','Find a biomedical entity, inspect its neighborhood, or look up a source publication.')
info=get_release()
entity_tab,paper_tab=st.tabs(['Entity Search','Paper Context'])
with entity_tab:
    from_home='search_prefill' in st.session_state
    if 'search_prefill' in st.session_state:
        st.session_state.entity_query=st.session_state.pop('search_prefill')
    with st.form('entity_search'):
        query=st.text_input('Entity name',key='entity_query',placeholder='e.g. smoking, diabetes, APOE',max_chars=200)
        submitted=st.form_submit_button('Search entities',type='primary')
    if submitted or from_home:
        previous_key=f"basic_selected_{st.session_state.get('basic_search_revision',0)}"
        st.session_state.basic_search_revision=st.session_state.get('basic_search_revision',0)+1
        for key in ['basic_result',previous_key,'basic_loaded_id','entity_matches']:
            st.session_state.pop(key,None)
        if not query.strip():
            st.warning('Enter an entity name.')
        else:
            try:
                with st.spinner('Finding entities…'):
                    st.session_state.entity_matches=api('entities/search',params={'q':query})
            except ServiceError as exc:
                st.error(str(exc))
    matches=st.session_state.get('entity_matches')
    if matches:
        nodes=matches['nodes']
        if not nodes:
            st.info('No matching entities. Try another term or spelling.')
        else:
            if matches['suggestions']:
                st.info('No direct match. These names may be related to your search.')
            lookup={n['id']:n for n in nodes}
            selected=st.selectbox('Matched entities',list(lookup),index=0,format_func=lambda k:f"{lookup[k]['name']} · {lookup[k]['type']}",key=f"basic_selected_{st.session_state.get('basic_search_revision',0)}")
            if st.session_state.get('basic_loaded_id') != selected or 'basic_result' not in st.session_state:
                try:
                    with st.spinner('Loading the one-hop neighborhood…'):
                        st.session_state.basic_result=api(f'entities/{selected}/neighbors')
                        st.session_state.basic_loaded_id=selected
                except ServiceError as exc:
                    st.error(str(exc))
            if st.session_state.get('basic_loaded_id')==selected and 'basic_result' in st.session_state:
                st.subheader(lookup[selected]['name'])
                entity=lookup[selected]
                st.caption(f"{entity['type']} — {TYPE_NAMES.get(entity['type'], entity['type'])} · Entity ID: {selected}")
                st.caption('One-hop neighborhood · Up to 200 relationship records, ordered by neighbor degree.')
                show_graph(st.session_state.basic_result,'basic',info['export_enabled'])
with paper_tab:
    with st.form('paper_search'):
        pmc=st.text_input('PMCID',placeholder='e.g. PMC10948909',max_chars=30)
        paper_submit=st.form_submit_button('Find paper',type='primary')
    if paper_submit:
        st.session_state.paper_lookup=pmc.strip().upper()
    if st.session_state.get('paper_lookup'):
        show_paper(st.session_state.paper_lookup,'paper')
