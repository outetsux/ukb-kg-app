import streamlit as st
from frontend.client import api,ServiceError
from frontend.components import heading,get_release,show_graph,TYPE_NAMES
from frontend.entity_picker import entity_picker

heading('Subgraph Explorer','Choose one or two biomedical entities and explore connections in either direction.')
info=get_release()
with st.container(border=True):
    c1,c2=st.columns(2)
    with c1:sid=entity_picker('Entity A (required)','explorer_entity_a')
    with c2:eid=entity_picker('Entity B (optional)','explorer_entity_b',optional=True)
    entity_b=st.session_state.get('explorer_entity_b_state',{}).get('selected')
    if eid is not None and entity_b:
        st.session_state.explorer_locked_types=[entity_b['type']]
        types=st.multiselect('Entity B types',list(TYPE_NAMES),key='explorer_locked_types',
            disabled=True,format_func=lambda k:f'{k} — {TYPE_NAMES[k]}')
    else:
        # Keep the user's optional type filter when selecting and then clearing Entity B.
        if 'explorer_types' not in st.session_state:
            st.session_state.explorer_types=st.session_state.get('explorer_manual_types',[])
        types=st.multiselect('Entity B types',list(TYPE_NAMES),key='explorer_types',
            format_func=lambda k:f'{k} — {TYPE_NAMES[k]}')
        st.session_state.explorer_manual_types=list(types)
    relations=st.multiselect('Relationships',info['stats']['relation_types'],placeholder='All relationships')
    c1,c2,c3=st.columns(3)
    hops=c1.slider('Maximum hops',1,3,2)
    limit=c2.slider('Maximum paths',1,200,50)
    confidence=c3.slider('Minimum confidence score',0.0,1.0,0.0,.05)
    submitted=st.button('Explore connections',type='primary',disabled=sid is None)
    if submitted:
        st.session_state.pop('explorer_result',None)
        st.session_state.pop('explorer_error',None)
        try:
            with st.spinner('Finding paths…'):
                st.session_state.explorer_result=api('subgraph',{'start_id':sid,'end_id':eid,'target_types':types,'relationship_types':relations,'hops':hops,'limit':limit,'min_confidence':confidence})
        except ServiceError as exc:
            st.session_state.explorer_error=str(exc)
        # Render the completed request in a fresh run, clearing transient error/spinner elements.
        st.rerun()
    status=st.empty()
    if st.session_state.get('explorer_error'):
        status.error(st.session_state.explorer_error)
if 'explorer_result' in st.session_state:
    st.caption('Paths are returned shortest first. Connections and multi-hop paths do not establish causation.')
    show_graph(st.session_state.explorer_result,'explorer',info['export_enabled'])
