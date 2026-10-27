"""Inspect already retrieved paths without performing another retrieval/model call."""
import streamlit as st
from streamlit.components.v1 import html as iframe
from .components import graph_html, relationship_frame, evidence_selector


def selected_path_graph(data, selected):
    """None selects all paths; integers select one path by retrieval rank."""
    paths=data.get('paths',[])
    paths=paths if selected is None else [paths[selected]]
    source=data.get('path_graph',{})
    edge_ids={eid for path in paths for eid in path['edges']}
    edges=[edge for edge in source.get('edges',[]) if edge['id'] in edge_ids]
    node_ids={node for edge in edges for node in (edge['source'],edge['target'])}
    nodes=[node for node in source.get('nodes',[]) if node['id'] in node_ids]
    if edge_ids != {edge['id'] for edge in edges} or node_ids != {node['id'] for node in nodes}:
        return None  # Never reconstruct identities or provenance from path text.
    return {'nodes':nodes,'edges':edges,'paths':paths}


def show_path_evidence(data, key):
    paths=data.get('paths',[])
    if not paths:
        st.caption('No connecting paths were retrieved.')
        return
    with st.expander(f'All {len(paths)} retrieved paths'):
        for rank,path in enumerate(paths,1):
            st.text(f"{rank}. {path['text']}")
    selected=st.selectbox('Display paths',[None,*range(len(paths))],key=key+'_selection',
        format_func=lambda i:'All retrieved paths' if i is None else f'Path {i+1} · {len(paths[i]["edges"])} '+('hop' if len(paths[i]['edges'])==1 else 'hops'))
    graph=selected_path_graph(data,selected)
    if graph and graph['edges']:
        st.caption('Arrows show stored relationship directions. Paths are retrieved in either direction and do not imply causation. Drag nodes, zoom, or reset the view.')
        source,clipped=graph_html(graph,height=440,linear_path=selected is not None)
        iframe(source,height=455,scrolling=False)
        if clipped:
            st.info('Only part of the graph is displayed. Complete paths remain available above.')
        with st.expander('Relationships & source papers'):
            st.dataframe(relationship_frame(graph['edges']),hide_index=True,width='stretch',
                column_config={'Paper':st.column_config.LinkColumn(display_text='PMC')})
            evidence_selector(graph['edges'],key+'_source')
    else:
        st.info('Graph details are not available for these saved paths. Expand the retrieved paths above to read their text.')
    if selected is not None:
        st.code(paths[selected]['text'],language=None,wrap_lines=True)
