import streamlit as st
import pandas as pd
import altair as alt
from frontend.components import heading,get_release,metrics,COLORS
from shared.entity_types import definition_rows

heading('Graph Overview','A view of entities, relationships and publication coverage in this release.')
info=get_release()
stats=info['stats']
metrics(stats)
types=pd.DataFrame(stats['entity_types'])
colors=alt.Scale(domain=list(COLORS),range=list(COLORS.values()))
st.subheader('What is in the graph?')
chart=alt.Chart(types).mark_bar(cornerRadiusEnd=4).encode(y=alt.Y('type:N',sort='-x',title=None),
    x=alt.X('count:Q',title='Entities'),color=alt.Color('type:N',scale=colors,legend=None),
    tooltip=['type','name',alt.Tooltip('count:Q',format=',')]).properties(height=330)
st.altair_chart(chart,width='stretch')
with st.expander('Entity types and definitions'):
    st.table(pd.DataFrame(definition_rows(dict(zip(types['type'],types['count'])))).set_index('Abbr'))
st.subheader('How entity types connect')
heat=alt.Chart(pd.DataFrame(stats['connections'])).mark_rect().encode(
    x=alt.X('target:N',title='Target entity type'),y=alt.Y('source:N',title='Source entity type'),
    color=alt.Color('count:Q',scale=alt.Scale(scheme='tealblues'),title='Relationships'),
    tooltip=['source','target',alt.Tooltip('count:Q',format=',')]).properties(height=350)
st.altair_chart(heat,width='stretch')
with st.expander('Average degree by entity type'):
    st.altair_chart(alt.Chart(types).mark_circle(size=160).encode(x=alt.X('count:Q',title='Entities'),
        y=alt.Y('average_degree:Q',title='Average degree'),color=alt.Color('type:N',scale=colors),
        tooltip=['name','count','average_degree']),width='stretch')
st.caption(f"Release {info['version']}")
