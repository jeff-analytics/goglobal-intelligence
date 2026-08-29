import React,{useState} from 'react'
import {Sparkles} from 'lucide-react'
import {api} from '../api'
import {Button} from './Common'
import {localizeRuntimeMessage} from '../utils'
import {useI18n} from '../i18n.jsx'

function tokenText(n){
  const v=Number(n||0)
  return v>0?v.toLocaleString():''
}


function hasOriginSupplyGap(value){
  const rows=value?.markets||[]
  return rows.some(row=>(row?.missing||row?.requested||row?.unsupported||[]).includes('origin_supply'))
}

function firstReason(result,locale){
  const rows=result?.markets||[]
  const raw=rows.flatMap(x=>x?.errors||[]).find(Boolean)||''
  if(!raw)return ''
  return localizeRuntimeMessage(String(raw).replace(/^[a-z_]+:\s*/i,''),locale)
}

function resultText(result,locale){
  const s=result?.summary||{}
  if(result?.status==='needs_hs') return locale==='zh'?'HS 待确认 · 未调用模型':'HS pending · no model call'
  if(Number(s.requested||0)===0) return locale==='zh'?'数据已完整 · 未调用模型':'Data complete · no model call'
  if(result?.status==='unsupported' && hasOriginSupplyGap(result)) return locale==='zh'?'供给证据缺失 · 请同步供应证据 · 未调用模型':'Supply evidence missing · sync supply evidence · no model call'
  if(result?.status==='unsupported') return locale==='zh'?'当前模型无法检索这些缺口 · 未调用模型':'Current model cannot research these gaps · no model call'
  const saved=Number(s.saved||0),applied=Number(s.applied||0),prices=Number(s.prices||0),failures=Number(s.failures||0)
  const calls=Number(s.model_calls||0),tokens=Number(s.total_tokens||0)
  if(saved+prices>0){
    const parts=[locale==='zh'?`证据 ${saved}`:`Evidence ${saved}`]
    if(applied)parts.push(locale==='zh'?`应用 ${applied}`:`Applied ${applied}`)
    if(prices)parts.push(locale==='zh'?`价格 ${prices}`:`Prices ${prices}`)
    if(calls)parts.push(locale==='zh'?`模型调用 ${calls}`:`Model calls ${calls}`)
    if(tokens)parts.push(`${tokenText(tokens)} tokens`)
    if(failures)parts.push(locale==='zh'?`失败 ${failures}`:`Failed ${failures}`)
    if(hasOriginSupplyGap(result))parts.push(locale==='zh'?'供给仍需同步':'Supply sync still required')
    return parts.join(' · ')
  }
  const reason=firstReason(result,locale)
  const parts=[locale==='zh'?'未找到可验证数据':'No verified evidence']
  if(calls)parts.push(locale==='zh'?`模型调用 ${calls}`:`Model calls ${calls}`)
  if(tokens)parts.push(`${tokenText(tokens)} tokens`)
  if(reason)parts.push(reason)
  return parts.join(' · ')
}

function planText(plan,locale){
  const s=plan?.summary||{}
  if(plan?.status==='needs_hs')return locale==='zh'?'HS 待确认 · 未调用模型':'HS pending · no model call'
  if(plan?.status==='complete')return locale==='zh'?'数据已完整 · 未调用模型':'Data complete · no model call'
  if(plan?.status==='unsupported' && hasOriginSupplyGap(plan))return locale==='zh'?'供给证据缺失 · 请同步供应证据 · 未调用模型':'Supply evidence missing · sync supply evidence · no model call'
  if(plan?.status==='unsupported')return locale==='zh'?'当前模型无法检索这些缺口 · 未调用模型':'Current model cannot research these gaps · no model call'
  const calls=Number(s.max_model_calls||0),cats=Number(s.categories||0)
  return locale==='zh'?`缺失 ${cats} 类 · 最多 ${calls} 次模型调用`:`${cats} missing categories · up to ${calls} model call(s)`
}

export function AiRecoveryAction({project,scope='all',markets=null,onComplete,label,variant='secondary',disabled=false}){
  const {locale}=useI18n()
  const [loading,setLoading]=useState(false)
  const [feedback,setFeedback]=useState(null)

  function queryString(){
    const qs=new URLSearchParams({scope})
    if(markets?.length)qs.set('market_codes',markets.join(','))
    return qs.toString()
  }

  async function run(){
    if(!project?.id)return
    setLoading(true);setFeedback(null)
    try{
      // Free local guard first. If there is a real gap, execute immediately in
      // the same click. The user should not have to understand a two-click state
      // machine just to recover missing data.
      const plan=await api(`/api/projects/${project.id}/ai/plan?${queryString()}`)
      const calls=Number(plan?.summary?.max_model_calls||0)
      if(!calls){
        setFeedback({tone:plan?.status==='complete'?'success':'warning',text:planText(plan,locale)})
        return
      }
      const result=await api(`/api/projects/${project.id}/ai/recover-all?${queryString()}`,{method:'POST'})
      setFeedback({tone:(result.status==='recovered'||result.status==='complete')?'success':result.status==='failed'?'danger':'warning',text:resultText(result,locale)})
      await onComplete?.(result)
    }catch(e){
      setFeedback({tone:'danger',text:localizeRuntimeMessage(e.message,locale)})
    }finally{setLoading(false)}
  }

  return <div className="ai-action-control"><Button icon={Sparkles} variant={variant} loading={loading} disabled={disabled||!project?.id} onClick={run}>{label||(locale==='zh'?'AI 补全':'AI recovery')}</Button>{feedback&&<button className={`ai-action-result ${feedback.tone}`} onClick={()=>setFeedback(null)} title={feedback.text}>{feedback.text}</button>}</div>
}

export function PortfolioAiRecoveryAction({onComplete,label}){
  const {locale}=useI18n();const [loading,setLoading]=useState(false);const [feedback,setFeedback]=useState(null)
  async function run(){
    setLoading(true);setFeedback(null)
    try{
      const plan=await api('/api/portfolio/ai/plan')
      const calls=Number(plan?.summary?.max_model_calls||0)
      if(!calls){setFeedback({tone:'success',text:locale==='zh'?'没有可补全的数据缺口':'No recoverable data gaps'});return}
      const result=await api('/api/portfolio/ai/recover',{method:'POST'})
      const s=result?.summary||{};const mc=Number(s.model_calls||0),tokens=Number(s.total_tokens||0)
      const parts=[locale==='zh'?`项目 ${s.projects||0}`:`Projects ${s.projects||0}`,locale==='zh'?`证据 ${s.saved||0}`:`Evidence ${s.saved||0}`,locale==='zh'?`应用 ${s.applied||0}`:`Applied ${s.applied||0}`]
      if(s.prices)parts.push(locale==='zh'?`价格 ${s.prices}`:`Prices ${s.prices}`)
      if(mc)parts.push(locale==='zh'?`模型调用 ${mc}`:`Model calls ${mc}`)
      if(tokens)parts.push(`${tokenText(tokens)} tokens`)
      if(s.failures)parts.push(locale==='zh'?`失败 ${s.failures}`:`Failed ${s.failures}`)
      setFeedback({tone:s.failures?'warning':'success',text:parts.join(' · ')});await onComplete?.(result)
    }catch(e){setFeedback({tone:'danger',text:localizeRuntimeMessage(e.message,locale)})}finally{setLoading(false)}
  }
  return <div className="ai-action-control"><Button icon={Sparkles} variant="secondary" loading={loading} onClick={run}>{label||(locale==='zh'?'AI 批量补全':'AI batch recovery')}</Button>{feedback&&<button className={`ai-action-result ${feedback.tone}`} onClick={()=>setFeedback(null)}>{feedback.text}</button>}</div>
}
