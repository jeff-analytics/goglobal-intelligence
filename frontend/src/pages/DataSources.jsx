import React, { useEffect, useMemo, useState } from 'react'
import { BrainCircuit, CheckCircle2, ChevronDown, Database, Eye, EyeOff, Globe2, KeyRound, RefreshCw, Search, ShieldCheck, Sparkles, Wrench } from 'lucide-react'
import { api } from '../api'
import { Badge, Button, Card, ErrorBanner, PageHeader } from '../components/Common'
import { useI18n } from '../i18n.jsx'

function SecretField({ label, value, onChange, placeholder, visible, onToggle }) {
  return <label className="api-field api-secret-field"><span>{label}</span><div className="api-secret-input"><input type={visible?'text':'password'} value={value} onChange={e=>onChange(e.target.value)} placeholder={placeholder} autoComplete="new-password"/><button type="button" onClick={onToggle} aria-label={visible?'Hide secret':'Show secret'}>{visible?<EyeOff size={16}/>:<Eye size={16}/>}</button></div></label>
}

function ConfigStatus({ configured, locale }) {
  return <Badge tone={configured?'success':'neutral'}>{configured?(locale==='zh'?'已配置':'Configured'):(locale==='zh'?'未配置':'Not configured')}</Badge>
}

function Feedback({ value }) {
  if(!value) return null
  return <div className={`api-feedback ${value.ok?'ok':'bad'}`}>{value.ok?<CheckCircle2 size={16}/>:<span className="api-feedback-dot">!</span>}<div><b>{value.title}</b>{value.detail&&<span>{value.detail}</span>}</div></div>
}

const PRESETS={
  deepseek:{provider:'DeepSeek',protocol:'openai_compatible',base_url:'https://api.deepseek.com'},
  openai:{provider:'OpenAI',protocol:'openai_responses',base_url:'https://api.openai.com/v1'},
  anthropic:{provider:'Anthropic',protocol:'anthropic',base_url:'https://api.anthropic.com/v1'},
  gemini:{provider:'Google Gemini',protocol:'gemini',base_url:'https://generativelanguage.googleapis.com/v1beta'},
  custom:{provider:'',protocol:'',base_url:''},
}

function presetKey(ai){
  const p=(ai?.provider||'').toLowerCase();const b=(ai?.base_url||'').toLowerCase()
  if(p.includes('deepseek')||b.includes('deepseek'))return 'deepseek'
  if(p==='openai'||b.includes('openai.com'))return 'openai'
  if(p.includes('anthropic')||b.includes('anthropic'))return 'anthropic'
  if(p.includes('gemini')||b.includes('googleapis'))return 'gemini'
  return 'custom'
}

function Capability({ ok, icon:Icon, title, detail, locale }){
  return <div className={`capability-tile ${ok?'ready':'muted'}`}><div className="capability-icon"><Icon size={16}/></div><div><b>{title}</b><span>{detail}</span></div><Badge tone={ok?'success':'neutral'}>{ok?(locale==='zh'?'已就绪':'Ready'):'—'}</Badge></div>
}

export default function DataSources() {
  const { t, locale } = useI18n()
  const [apiConfig,setApiConfig]=useState(null)
  const [models,setModels]=useState({available:[],selected:'',source:'not-loaded'})
  const [refreshing,setRefreshing]=useState(false)
  const [busy,setBusy]=useState({})
  const [show,setShow]=useState({comtrade:false,ebay:false,ai:false,research:false})
  const [feedback,setFeedback]=useState({})
  const [error,setError]=useState('')
  const [advanced,setAdvanced]=useState(false)
  const [providerPreset,setProviderPreset]=useState('custom')
  const [forms,setForms]=useState({
    comtrade:{api_key:''},
    ebay:{environment:'sandbox',client_id:'',client_secret:'',marketplace_id:''},
    ai:{provider:'',protocol:'',base_url:'',api_key:'',model:''},
    research:{provider:'auto',api_key:'',base_url:'https://api.tavily.com'},
  })

  useEffect(()=>{ refreshAll() },[])
  function setBusyKey(key,value){setBusy(x=>({...x,[key]:value}))}
  function setNote(key,value){setFeedback(x=>({...x,[key]:value}))}
  function aiPayload(){return {...forms.ai}}

  async function refreshAll(){
    setRefreshing(true);setError('')
    try{
      const c=await api('/api/local-config/apis');setApiConfig(c);setProviderPreset(presetKey(c.ai))
      setForms(f=>({...f,
        ebay:{...f.ebay,environment:c.ebay?.environment||'sandbox',marketplace_id:c.ebay?.marketplace_id||''},
        ai:{...f.ai,provider:c.ai?.provider||'',protocol:c.ai?.protocol||'',base_url:c.ai?.base_url||'',model:c.ai?.model||''},
        research:{...f.research,provider:c.research?.provider||'auto',base_url:c.research?.base_url||'https://api.tavily.com'},
      }))
    }catch(e){setError(e.message)}finally{setRefreshing(false)}
  }

  async function refreshConfigOnly(){
    const c=await api('/api/local-config/apis');setApiConfig(c);setProviderPreset(presetKey(c.ai))
    setForms(f=>({...f,
      ebay:{...f.ebay,environment:c.ebay?.environment||'sandbox',marketplace_id:c.ebay?.marketplace_id||''},
      ai:{...f.ai,provider:c.ai?.provider||f.ai.provider,protocol:c.ai?.protocol||f.ai.protocol,base_url:c.ai?.base_url||f.ai.base_url,model:c.ai?.model||f.ai.model},
      research:{...f.research,provider:c.research?.provider||f.research.provider,base_url:c.research?.base_url||f.research.base_url},
    }))
  }

  function applyPreset(key){
    setProviderPreset(key);const p=PRESETS[key]||PRESETS.custom
    if(key==='custom')return
    setForms(f=>({...f,ai:{...f.ai,...p,model:''}}));setModels({available:[],selected:'',source:'not-loaded'})
  }

  async function loadModels(){
    if(!forms.ai.protocol.trim()){setNote('ai',{ok:false,title:locale==='zh'?'接口协议未选择':'API protocol not selected'});return}
    if(!forms.ai.base_url.trim()){setNote('ai',{ok:false,title:locale==='zh'?'API Base URL 为空':'API Base URL is empty'});return}
    setBusyKey('models',true);setNote('ai',null)
    try{
      const result=await api('/api/local-config/ai/models',{method:'POST',body:JSON.stringify(aiPayload())});setModels(result||{available:[],selected:'',source:'unavailable'})
      const count=(result?.available||[]).length
      setNote('ai',result?.warning?{ok:false,title:locale==='zh'?'模型列表读取失败':'Could not load models',detail:result.warning}:{ok:true,title:locale==='zh'?`已加载 ${count} 个模型`:`Loaded ${count} models`})
    }catch(e){setNote('ai',{ok:false,title:locale==='zh'?'模型列表读取失败':'Could not load models',detail:e.message})}finally{setBusyKey('models',false)}
  }

  async function saveComtrade(){
    setBusyKey('comtrade',true);setNote('comtrade',null)
    try{const test=await api('/api/local-config/comtrade/validate',{method:'POST',body:JSON.stringify(forms.comtrade)});await api('/api/local-config/comtrade',{method:'POST',body:JSON.stringify(forms.comtrade)});setForms(f=>({...f,comtrade:{api_key:''}}));setNote('comtrade',{ok:true,title:locale==='zh'?'已保存并连接成功':'Saved and connected',detail:locale==='zh'?`测试记录 ${test.records}`:`${test.records} test records`});await refreshConfigOnly()}
    catch(e){setNote('comtrade',{ok:false,title:locale==='zh'?'保存或连接失败':'Save or connection failed',detail:e.message})}finally{setBusyKey('comtrade',false)}
  }

  async function saveEbay(){
    setBusyKey('ebay',true);setNote('ebay',null)
    try{const test=await api('/api/local-config/ebay/validate',{method:'POST',body:JSON.stringify(forms.ebay)});await api('/api/local-config/ebay',{method:'POST',body:JSON.stringify(forms.ebay)});setForms(f=>({...f,ebay:{...f.ebay,client_id:'',client_secret:''}}));setNote('ebay',{ok:true,title:locale==='zh'?'已保存并通过 OAuth':'Saved and OAuth verified',detail:`${test.environment} · OAuth`});await refreshConfigOnly()}
    catch(e){setNote('ebay',{ok:false,title:locale==='zh'?'OAuth 验证失败':'OAuth validation failed',detail:e.message})}finally{setBusyKey('ebay',false)}
  }

  async function saveAI(){
    if(!forms.ai.protocol.trim()||!forms.ai.base_url.trim()||!forms.ai.model.trim()){setNote('ai',{ok:false,title:locale==='zh'?'请补全模型配置':'Complete the model configuration'});return}
    setBusyKey('ai',true);setNote('ai',null)
    try{const test=await api('/api/local-config/ai/validate',{method:'POST',body:JSON.stringify(aiPayload())});await api('/api/local-config/ai',{method:'POST',body:JSON.stringify(aiPayload())});setForms(f=>({...f,ai:{...f.ai,api_key:''}}));setNote('ai',{ok:true,title:test.verified?(locale==='zh'?'已保存并验证':'Saved and verified'):(locale==='zh'?'已保存':'Saved'),detail:test.verified?`${test.provider} · ${test.model} · ${locale==='zh'?'未生成内容':'no generation'}`:(locale==='zh'?'模型列表端点不可用 · 未发送生成请求':'Model-list endpoint unavailable · no generation request sent')});await refreshConfigOnly()}
    catch(e){setNote('ai',{ok:false,title:locale==='zh'?'验证失败':'Validation failed',detail:e.message})}finally{setBusyKey('ai',false)}
  }

  async function testAI(){
    setBusyKey('aiTest',true);setNote('ai',null)
    try{const result=await api('/api/local-config/ai/validate',{method:'POST',body:JSON.stringify(aiPayload())});setNote('ai',{ok:true,title:result.verified?(locale==='zh'?'连接正常':'Connection ready'):(locale==='zh'?'配置可保存':'Configuration accepted'),detail:result.verified?`${result.provider} · ${result.model} · ${locale==='zh'?'未生成内容':'no generation'}`:(locale==='zh'?'未发送生成请求':'no generation request sent')})}
    catch(e){setNote('ai',{ok:false,title:locale==='zh'?'连接测试失败':'Connection test failed',detail:e.message})}finally{setBusyKey('aiTest',false)}
  }

  async function saveResearch(){
    setBusyKey('research',true);setNote('research',null)
    try{await api('/api/local-config/research',{method:'POST',body:JSON.stringify(forms.research)});setForms(f=>({...f,research:{...f.research,api_key:''}}));setNote('research',{ok:true,title:locale==='zh'?'联网研究配置已保存':'Web research saved'});await refreshConfigOnly()}
    catch(e){setNote('research',{ok:false,title:locale==='zh'?'保存失败':'Save failed',detail:e.message})}finally{setBusyKey('research',false)}
  }

  async function testResearch(){
    setBusyKey('researchTest',true);setNote('research',null)
    try{const r=await api('/api/local-config/research/validate',{method:'POST',body:JSON.stringify(forms.research)});setNote('research',{ok:true,title:locale==='zh'?'联网研究可用':'Web research ready',detail:r.provider==='native'?(locale==='zh'?'使用模型原生联网能力，不发送生成请求':'Provider-native research is available; no generation request sent'):`${r.provider}${r.results!=null?` · ${r.results} result`:''}`})}
    catch(e){setNote('research',{ok:false,title:locale==='zh'?'联网研究测试失败':'Web research test failed',detail:e.message})}finally{setBusyKey('researchTest',false)}
  }

  async function testOnly(key){
    if(key==='ai'){await testAI();return}
    setBusyKey(`${key}Test`,true);setNote(key,null)
    try{const result=key==='ebay'?await api('/api/local-config/ebay/validate',{method:'POST',body:JSON.stringify(forms.ebay)}):await api('/api/local-config/comtrade/validate',{method:'POST',body:JSON.stringify(forms.comtrade)});const detail=key==='ebay'?`${result.environment} · OAuth`:locale==='zh'?`测试记录 ${result.records}`:`${result.records} test records`;setNote(key,{ok:true,title:locale==='zh'?'连接正常':'Connection ready',detail})}
    catch(e){setNote(key,{ok:false,title:locale==='zh'?'连接测试失败':'Connection test failed',detail:e.message})}finally{setBusyKey(`${key}Test`,false)}
  }

  const modelOptions=useMemo(()=>(models.available||[]).map(id=>({id,label:id})),[models.available])
  const caps=apiConfig?.research?.capabilities||apiConfig?.ai?.research||{}
  const nativeReady=Boolean(caps.native_available)
  const webReady=Boolean(caps.web_search_available)
  const activeResearch=caps.active_provider||apiConfig?.research?.active_provider||'none'

  return <div className="page-stack">
    <PageHeader title={t('dataSources')} actions={<Button icon={RefreshCw} loading={refreshing} onClick={refreshAll}>{locale==='zh'?'刷新状态':'Refresh status'}</Button>} />
    <ErrorBanner error={error}/>

    <Card className="ai-research-overview">
      <div className="ai-research-overview-head"><div><span className="eyebrow">{locale==='zh'?'AI 与研究':'AI & Research'}</span><h2>{locale==='zh'?'AI 与联网研究':'AI & web research'}</h2></div><Badge tone={caps.decision_agent?'success':'neutral'}>{locale==='zh'?'决策智能体':'Decision Agent'}</Badge></div>
      <div className="capability-grid">
        <Capability ok={Boolean(apiConfig?.ai?.configured)} icon={BrainCircuit} title={locale==='zh'?'模型推理':'Model reasoning'} detail={apiConfig?.ai?.model||'—'} locale={locale}/>
        <Capability ok={Boolean(caps.structured_output)} icon={Wrench} title={locale==='zh'?'结构化输出':'Structured output'} detail={apiConfig?.ai?.protocol||'—'} locale={locale}/>
        <Capability ok={webReady} icon={Globe2} title={locale==='zh'?'联网研究':'Web research'} detail={activeResearch==='native'?(locale==='zh'?'模型原生联网':'Provider-native'):activeResearch==='tavily'?'Tavily':(locale==='zh'?'未启用':'Disabled')} locale={locale}/>
        <Capability ok={Boolean(caps.protected_user_inputs)} icon={ShieldCheck} title={locale==='zh'?'用户数据保护':'Protected inputs'} detail={locale==='zh'?'AI 不覆盖用户确认数据':'AI cannot silently overwrite user-confirmed data'} locale={locale}/>
      </div>
    </Card>

    <div className="api-config-grid">
      <Card className="api-config-card">
        <div className="api-config-head"><div className="api-brand-icon"><Database size={18}/></div><div><h2>UN Comtrade</h2></div><ConfigStatus configured={apiConfig?.comtrade?.configured} locale={locale}/></div>
        <div className="api-current"><span>API Key</span><b>{apiConfig?.comtrade?.api_key_masked||'—'}</b></div>
        <SecretField label="API Key" value={forms.comtrade.api_key} onChange={v=>setForms(f=>({...f,comtrade:{api_key:v}}))} visible={show.comtrade} onToggle={()=>setShow(x=>({...x,comtrade:!x.comtrade}))}/>
        <div className="api-config-actions"><Button variant="primary" icon={KeyRound} loading={busy.comtrade} onClick={saveComtrade}>{locale==='zh'?'保存并测试':'Save & test'}</Button><Button loading={busy.comtradeTest} onClick={()=>testOnly('comtrade')}>{locale==='zh'?'仅测试':'Test only'}</Button></div><Feedback value={feedback.comtrade}/>
      </Card>

      <Card className="api-config-card api-config-card-wide">
        <div className="api-config-head"><div className="api-brand-icon"><Database size={18}/></div><div><h2>eBay</h2></div><ConfigStatus configured={apiConfig?.ebay?.configured} locale={locale}/></div>
        <div className="api-current api-current-3"><div><span>{locale==='zh'?'状态':'Status'}</span><b>{apiConfig?.ebay?.configured?(locale==='zh'?'已配置':'Configured'):(locale==='zh'?'未配置':'Not configured')}</b></div><div><span>Client ID</span><b>{apiConfig?.ebay?.client_id_masked||'—'}</b></div><div><span>{locale==='zh'?'当前环境':'Environment'}</span><b>{apiConfig?.ebay?.environment==='production'?'Production':'Sandbox'}</b></div></div>
        <div className="api-form-grid ebay-api-grid"><label className="api-field"><span>{locale==='zh'?'环境':'Environment'}</span><select value={forms.ebay.environment} onChange={e=>setForms(f=>({...f,ebay:{...f.ebay,environment:e.target.value}}))}><option value="sandbox">Sandbox</option><option value="production">Production</option></select></label><label className="api-field"><span>Client ID</span><input value={forms.ebay.client_id} onChange={e=>setForms(f=>({...f,ebay:{...f.ebay,client_id:e.target.value}}))} autoComplete="off"/></label><SecretField label="Client Secret" value={forms.ebay.client_secret} onChange={v=>setForms(f=>({...f,ebay:{...f.ebay,client_secret:v}}))} visible={show.ebay} onToggle={()=>setShow(x=>({...x,ebay:!x.ebay}))}/><label className="api-field"><span>{locale==='zh'?'默认站点':'Default marketplace'}</span><input value={forms.ebay.marketplace_id} onChange={e=>setForms(f=>({...f,ebay:{...f.ebay,marketplace_id:e.target.value}}))}/></label></div>
        <div className="api-config-actions"><Button variant="primary" icon={KeyRound} loading={busy.ebay} onClick={saveEbay}>{locale==='zh'?'保存并验证 OAuth':'Save & verify OAuth'}</Button><Button loading={busy.ebayTest} onClick={()=>testOnly('ebay')}>{locale==='zh'?'仅测试':'Test only'}</Button></div><Feedback value={feedback.ebay}/>
      </Card>

      <Card className="api-config-card api-config-card-wide model-service-card">
        <div className="api-config-head"><div className="api-brand-icon"><Sparkles size={18}/></div><div><h2>{locale==='zh'?'AI 模型':'AI model'}</h2></div><div className="api-head-status"><ConfigStatus configured={apiConfig?.ai?.configured} locale={locale}/>{nativeReady&&<Badge tone="success">{locale==='zh'?'原生联网可用':'Native web available'}</Badge>}</div></div>
        <div className="provider-preset-row"><label className="api-field"><span>{locale==='zh'?'模型服务商':'Model provider'}</span><select value={providerPreset} onChange={e=>applyPreset(e.target.value)}><option value="deepseek">DeepSeek</option><option value="openai">OpenAI</option><option value="anthropic">Anthropic</option><option value="gemini">Google Gemini</option><option value="custom">{locale==='zh'?'自定义兼容服务':'Custom compatible service'}</option></select></label><label className="api-field api-model-field"><span>{locale==='zh'?'模型':'Model'}</span><input list="model-api-options" value={forms.ai.model} onChange={e=>setForms(f=>({...f,ai:{...f.ai,model:e.target.value}}))} placeholder={locale==='zh'?'输入模型 ID 或加载模型列表':'Enter model ID or load models'}/><datalist id="model-api-options">{modelOptions.map(x=><option key={x.id} value={x.id}>{x.label}</option>)}</datalist></label><SecretField label="API Key" value={forms.ai.api_key} onChange={v=>setForms(f=>({...f,ai:{...f.ai,api_key:v}}))} visible={show.ai} onToggle={()=>setShow(x=>({...x,ai:!x.ai}))}/></div>
        <button className="advanced-toggle" type="button" onClick={()=>setAdvanced(!advanced)}><ChevronDown size={15} className={advanced?'rotated':''}/>{locale==='zh'?'高级连接配置':'Advanced connection settings'}</button>
        {advanced&&<div className="api-form-grid model-api-grid"><label className="api-field"><span>{locale==='zh'?'服务商名称':'Provider name'}</span><input value={forms.ai.provider} onChange={e=>setForms(f=>({...f,ai:{...f.ai,provider:e.target.value}}))}/></label><label className="api-field"><span>{locale==='zh'?'接口协议':'API protocol'}</span><select value={forms.ai.protocol} onChange={e=>{setForms(f=>({...f,ai:{...f.ai,protocol:e.target.value}}));setModels({available:[],selected:'',source:'not-loaded'})}}><option value="">—</option><option value="openai_compatible">Chat Completions compatible</option><option value="openai_responses">Responses API</option><option value="anthropic">Anthropic Messages</option><option value="gemini">Gemini GenerateContent</option></select></label><label className="api-field model-base-url"><span>API Base URL</span><input value={forms.ai.base_url} onChange={e=>setForms(f=>({...f,ai:{...f.ai,base_url:e.target.value}}))} autoComplete="off"/></label></div>}
        <div className="api-config-actions"><Button variant="primary" icon={KeyRound} loading={busy.ai} onClick={saveAI}>{locale==='zh'?'保存并验证':'Save & verify'}</Button><Button loading={busy.aiTest} onClick={()=>testOnly('ai')}>{locale==='zh'?'仅测试':'Test only'}</Button><Button icon={RefreshCw} loading={busy.models} onClick={loadModels}>{locale==='zh'?'加载可用模型':'Load models'}</Button></div><Feedback value={feedback.ai}/>
      </Card>

      <Card className="api-config-card api-config-card-wide research-service-card">
        <div className="api-config-head"><div className="api-brand-icon"><Search size={18}/></div><div><h2>{locale==='zh'?'联网研究':'Web research'}</h2></div><div className="api-head-status"><ConfigStatus configured={webReady} locale={locale}/><Badge tone={activeResearch==='native'||activeResearch==='tavily'?'success':'neutral'}>{activeResearch==='native'?(locale==='zh'?'模型原生':'Provider-native'):activeResearch==='tavily'?'Tavily':(locale==='zh'?'未联网':'Offline')}</Badge></div></div>
        <div className="research-provider-grid"><label className="api-field"><span>{locale==='zh'?'研究方式':'Research mode'}</span><select value={forms.research.provider} onChange={e=>setForms(f=>({...f,research:{...f.research,provider:e.target.value}}))}><option value="auto">{locale==='zh'?'自动选择（推荐）':'Auto select (recommended)'}</option><option value="native">{locale==='zh'?'模型原生联网':'Provider-native web search'}</option><option value="tavily">Tavily</option><option value="none">{locale==='zh'?'关闭联网':'Disable web research'}</option></select></label>{forms.research.provider==='tavily'||forms.research.provider==='auto'?<><SecretField label="Tavily API Key" value={forms.research.api_key} onChange={v=>setForms(f=>({...f,research:{...f.research,api_key:v}}))} visible={show.research} onToggle={()=>setShow(x=>({...x,research:!x.research}))}/><label className="api-field"><span>Tavily Base URL</span><input value={forms.research.base_url} onChange={e=>setForms(f=>({...f,research:{...f.research,base_url:e.target.value}}))}/></label></>:null}</div>
        <div className="api-config-actions"><Button variant="primary" icon={KeyRound} loading={busy.research} onClick={saveResearch}>{locale==='zh'?'保存研究配置':'Save research settings'}</Button><Button loading={busy.researchTest} onClick={testResearch}>{locale==='zh'?'测试联网研究':'Test web research'}</Button></div><Feedback value={feedback.research}/>
      </Card>
    </div>
  </div>
}
