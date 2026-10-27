"""Keyboard-accessible, debounced entity combobox; browser never contacts the backend."""
from pathlib import Path
import streamlit as st
import streamlit.components.v1 as components
from .client import api, ServiceError

_component=components.declare_component('ukb_entity_picker',path=str(Path(__file__).parent/'entity_picker'))


def entity_picker(label,key,optional=False):
    state=st.session_state.setdefault(key+'_state',{'query':'','nodes':[],'selected':None,'event_id':None,'error':'','suggestions':False})
    value=_component(label=label,optional=optional,query=state['query'],nodes=state['nodes'],
                     selected=state['selected'],error=state['error'],suggestions=state['suggestions'],
                     event_id=state['event_id'],key=key,default=None)
    if isinstance(value,dict) and value.get('event_id')!=state['event_id']:
        state['event_id']=value.get('event_id')
        kind=value.get('kind')
        if kind in {'search','clear'}:
            query=str(value.get('query',''))[:200] if kind=='search' else ''
            state.update(query=query,selected=None,nodes=[],error='',suggestions=False)
            if query.strip():
                try:
                    result=api('entities/search',params={'q':query})
                    state.update(nodes=result['nodes'],suggestions=result['suggestions'])
                except ServiceError as exc:state['error']=str(exc)
        elif kind=='select':
            chosen=next((n for n in state['nodes'] if n['id']==value.get('id')),None)
            state.update(selected=chosen,query=chosen['name'] if chosen else '',error='')
            if chosen is None:state['nodes']=[]
        st.rerun()
    return state['selected']['id'] if state['selected'] else None
