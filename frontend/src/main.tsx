import React from 'react'
import ReactDOM from 'react-dom/client'
import '@xyflow/react/dist/style.css'
import './styles.css'
import App from './App'
import { ToastProvider } from './ui'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ToastProvider><App /></ToastProvider>
  </React.StrictMode>,
)
