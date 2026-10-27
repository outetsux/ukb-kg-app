import streamlit as st
from openai import AuthenticationError,RateLimitError,APITimeoutError,APIError
from frontend.client import api,providers,ServiceError
from frontend.components import heading,relationship_frame,evidence_selector
from frontend.llm import filter_entities,answer
from frontend.path_evidence import show_path_evidence

heading('Chat','Ask a research question with optional context retrieved from UKB-KG.')
st.session_state.setdefault('chat_turns',[])
if st.session_state.pop('chat_reset_rag',False):
    st.session_state.chat_use_rag=False
try:
    options=providers()
except ServiceError as exc:
    st.error(str(exc));st.stop()

# This state is not owned by a widget, so Streamlit keeps it when navigating away.
connection=st.session_state.setdefault('chat_connection',{
    'provider':st.session_state.get('chat_provider',options[0]['name']),
    'api_key':st.session_state.get('chat_api_key',''),
    'model':st.session_state.get('chat_model',options[0]['default_model']),
    'effort':st.session_state.get('chat_effort','default')})
if connection['provider'] not in [p['name'] for p in options]:
    connection.update(provider=options[0]['name'],api_key='',model=options[0]['default_model'],effort='default')
selected_provider=next(p for p in options if p['name']==connection['provider'])
if connection['model'] not in selected_provider['models']:
    connection['model']=selected_provider['default_model']
for field,widget in [('provider','chat_provider'),('api_key','chat_api_key'),('model','chat_model'),('effort','chat_effort')]:
    st.session_state[widget]=connection[field]

def clear_model_error():
    failed=st.session_state.pop('chat_failed',None)
    if failed:
        # Prefill for an explicit resend; never silently retry a charged model request.
        st.session_state.chat_question=failed['question']

def save_connection(field,widget):
    st.session_state.chat_connection[field]=st.session_state[widget]
    clear_model_error()

def provider_changed():
    name=st.session_state.chat_provider
    chosen=next(p for p in options if p['name']==name)
    st.session_state.chat_connection.update(provider=name,api_key='',model=chosen['default_model'],effort='default')
    st.session_state.chat_api_key=''
    st.session_state.chat_model=chosen['default_model']
    st.session_state.chat_effort='default'
    clear_model_error()

def clear_credentials():
    st.session_state.chat_connection['api_key']=''
    st.session_state.chat_api_key=''
    clear_model_error()

def new_conversation():
    st.session_state.chat_turns=[]
    st.session_state.chat_use_rag=False
    st.session_state.chat_question=''
    st.session_state.pop('chat_pending',None)
    st.session_state.pop('chat_failed',None)

with st.container(border=True):
    with st.expander('Model connection',expanded=not bool(st.session_state.get('chat_api_key'))):
        provider_name=st.selectbox('Service provider',[p['name'] for p in options],on_change=provider_changed,key='chat_provider')
        provider=next(p for p in options if p['name']==provider_name)
        c1,c2=st.columns(2)
        key=c1.text_input('API Key',type='password',key='chat_api_key',on_change=save_connection,args=('api_key','chat_api_key')).strip()
        model=c2.selectbox('Model',provider['models'],key='chat_model',on_change=save_connection,args=('model','chat_model'))
        st.caption('Your key stays in this session and is sent only to the selected model service through this app. Questions are also sent to the retrieval service when graph context is enabled. Do not submit personal health records.')
        with st.popover('Advanced parameters'):
            effort=st.selectbox('Reasoning effort',['default','none','minimal','low','medium','high','xhigh'],help='Default omits this parameter. Other values must be supported by the selected model.',key='chat_effort',on_change=save_connection,args=('effort','chat_effort'))
        st.button('Clear credentials',on_click=clear_credentials)

def evidence(data,index):
    for warning in data.get('warnings',[]):
        st.info(warning)
    with st.expander('Retrieved evidence'):
        st.caption(f"Release {data['version']} · {data['context_tokens']:,} context tokens")
        st.markdown('**Matched graph entities**')
        st.write(', '.join(n['name'] for n in data['matched_entities']))
        a,b=st.tabs(['Neighbor-based Context','Path-based Context'])
        with a:
            if data['triples']:
                st.dataframe(relationship_frame(data['triples']),hide_index=True,width='stretch',column_config={'Paper':st.column_config.LinkColumn(display_text='PMC')})
                evidence_selector(data['triples'],f'chat_source_{index}')
            else:
                st.caption('No neighbor triples were retrieved.')
        with b:
            show_path_evidence(data,f'chat_paths_{index}')
        with st.expander('Exact graph context sent to the model'):
            st.code(data['context'],language=None)

with st.container(key='chat_history'):
    for i,turn in enumerate(st.session_state.chat_turns):
        with st.chat_message('user'):
            st.write(turn['question'])
        with st.chat_message('assistant'):
            st.caption('UKB-KG context' if turn['mode']=='rag' else 'General conversation')
            st.write(turn['answer'])
            if turn.get('evidence'):
                evidence(turn['evidence'],i)
    if not st.session_state.chat_turns:
        st.markdown('**Try a research question**')
        for i,text in enumerate(['What diseases are related to smoking?','How are diabetes and smoking connected?','What relationships link APOE to Alzheimer disease?']):
            if st.button(text,key=f'chat_example_{i}',disabled=not key):
                st.session_state.chat_question=text
    if st.session_state.get('chat_failed'):
        st.error(st.session_state.chat_failed['message'])
        if st.button('Edit and retry last question',disabled=not key):
            st.session_state.chat_question=st.session_state.chat_failed['question']
with st.container(border=True,key='chat_composer'):
    left,right=st.columns([1.5,1])
    rag=left.toggle('Use UKB-KG context for this question',value=False,key='chat_use_rag')
    with right.container(horizontal=True,horizontal_alignment='right'):
        st.button('New conversation',on_click=new_conversation)
    st.caption('Context is off by default for each question. Enable it when you want graph evidence.')
    prompt=st.chat_input('Ask a question; include explicit entity names for graph retrieval.',key='chat_question',
                         disabled=not bool(key),max_chars=2000)
if prompt:
    # Keep this submission's local choice, resetting the widget before the next render.
    st.session_state.chat_reset_rag=True
    data=None
    try:
        with st.status('Preparing your answer…',expanded=True) as status:
            if rag:
                st.write('Identifying biomedical entities…')
                candidates=api('entities/extract',{'question':prompt})['candidates']
                selected=filter_entities(provider,key,model,candidates,effort)
                st.write('Retrieving graph context…')
                data=api('rag/retrieve',{'question':prompt,'entities':selected})
                for warning in data.get('warnings',[]):
                    st.warning(warning)
                if not data['has_context']:
                    raise ValueError('No graph context was found. Retry with a more specific question or turn off UKB-KG context.')
            st.write('Generating an answer…')
            response=answer(provider,key,model,st.session_state.chat_turns,prompt,data['context'] if data else None,effort)
            if not response.strip():
                raise ValueError('The model returned an empty answer. Please retry.')
            status.update(label='Answer ready',state='complete')
        st.session_state.chat_turns.append({'question':prompt,'answer':response,'mode':'rag' if rag else 'plain','evidence':data})
        st.session_state.chat_turns = st.session_state.chat_turns[-12:]
        st.session_state.pop('chat_failed',None)
        st.rerun()
    except AuthenticationError:
        error='Model authentication failed. Check the API key and selected service.'
    except RateLimitError:
        error='The model service rate limit or quota was reached. Please retry later.'
    except APITimeoutError:
        error='The model service timed out. Please retry.'
    except (ServiceError,ValueError) as exc:
        error=str(exc)
    except APIError:
        error='The model request failed. Check model support and advanced settings, then retry.'
    except Exception:
        error='The request could not be completed. Please retry.'
    st.session_state.chat_failed={'question':prompt,'message':error}
    st.rerun()
