import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import './styles.css'
import { I18nProvider } from './i18n.jsx'

class AppErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }
  static getDerivedStateFromError(error) {
    return { error }
  }
  componentDidCatch(error, info) {
    console.error('GoGlobal Intelligence UI runtime error', error, info)
  }
  render() {
    if (this.state.error) {
      const zh = (localStorage.getItem('bm_locale') || 'zh') === 'zh'
      return <div className="runtime-error-screen">
        <div className="runtime-error-card">
          <h1>{zh?'GoGlobal Intelligence 页面错误':'GoGlobal Intelligence UI error'}</h1>
          
          <pre>{String(this.state.error?.message || this.state.error)}</pre>
          <button onClick={() => window.location.reload()}>{zh?'重新加载':'Reload application'}</button>
        </div>
      </div>
    }
    return this.props.children
  }
}

createRoot(document.getElementById('root')).render(
  <React.StrictMode><I18nProvider><AppErrorBoundary><App /></AppErrorBoundary></I18nProvider></React.StrictMode>
)
