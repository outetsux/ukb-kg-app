import streamlit as st
from frontend.components import theme, heading, get_release, metrics
from frontend.client import setting

st.set_page_config(page_title='UKB-KG · Research Platform',page_icon=':material/hub:',layout='wide')
theme()
st.logo('assets/logo.svg',size='large')

def home():
    heading('Explore UK Biobank Knowledge Graph',
        'Discover biomedical entities, inspect relationships and source publications, and ask research questions with knowledge graph context.',
        'UK BIOBANK KNOWLEDGE GRAPH')
    info=get_release()
    metrics(info['stats'])
    st.write('')
    st.subheader('Start with a question')
    cards=[('Find an entity','Search an entity and follow its relationships to source publications.','app_pages/search.py','Search the graph',':material/search:'),
           ('Explore connections','Build a focused subgraph around an entity or connect two concepts.','app_pages/explorer.py','Explore a subgraph',':material/hub:'),
           ('Ask with evidence','Use retrieved triples and paths as context for a research conversation.','app_pages/chat.py','Open Chat',':material/forum:')]
    for col,(title,body,page,label,icon) in zip(st.columns(3),cards):
        with col,st.container(border=True):
            st.subheader(title)
            st.write(body)
            st.page_link(page,label=label,icon=icon)
    st.write('')
    left,right=st.columns([1.4,1])
    with left:
        st.subheader('From publications to connected knowledge')
        st.write('UKB-KG organizes findings from UK Biobank-related literature into biomedical entities and relationships, enriched with publication and study-population information. External graph relationships extend its coverage.')
        st.caption('Literature collection → Knowledge extraction & refinement → Context enrichment → Graph retrieval')
    with right,st.container(border=True):
        st.markdown('**Try a familiar concept**')
        for term in ['smoking','diabetes','APOE']:
            if st.button(term,key='example_'+term,width='stretch'):
                st.session_state.search_prefill=term
                st.switch_page('app_pages/search.py')
    st.divider()
    st.caption(f"Release {info['version']} · Research use · Relationships may represent associations, not causation.")
    for label,key in [('Paper','UKB_PUBLICATION_URL'),('Project','UKB_PROJECT_URL')]:
        value=str(setting(key))
        if value.startswith('https://'):
            st.link_button(label,value)
    if setting('UKB_CITATION'):
        st.write(str(setting('UKB_CITATION')))
    if setting('UKB_CONTACT'):
        st.caption('Contact: '+str(setting('UKB_CONTACT')))

pages={'':[st.Page(home,title='Home',icon=':material/home:',default=True)],
       'KG Explore':[st.Page('app_pages/overview.py',title='Graph Overview',icon=':material/bar_chart:'),
                     st.Page('app_pages/search.py',title='Basic Search',icon=':material/search:'),
                     st.Page('app_pages/explorer.py',title='Subgraph Explorer',icon=':material/hub:')],
       'KG Assistant':[st.Page('app_pages/chat.py',title='Chat',icon=':material/forum:')]}
navigation=st.navigation(pages,position='sidebar',expanded=True)
with st.sidebar:
    st.caption('Connected evidence for research')
    st.caption('Publication release · 202603')
navigation.run()
