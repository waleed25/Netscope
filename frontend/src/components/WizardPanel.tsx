import React, { useEffect, useState } from 'react'
import { api, BASE } from '../lib/api'

interface WizardStep {
  id: string
  title: string
  tool: string
}

interface Wizard {
  name: string
  title: string
  description: string
  requires: string[]
  steps: WizardStep[]
}

interface StepEvent {
  type: 'step_start' | 'step_done' | 'step_error' | 'done' | 'ping' | 'error'
  step?: string
  title?: string
  result?: string
  message?: string
}

interface StepState {
  id: string
  title: string
  status: 'pending' | 'running' | 'done' | 'error'
  result?: string
  error?: string
}

export default function WizardPanel() {
  const [wizards, setWizards] = useState<Wizard[]>([])
  const [selected, setSelected] = useState<Wizard | null>(null)
  const [running, setRunning] = useState(false)
  const [steps, setSteps] = useState<StepState[]>([])
  const [done, setDone] = useState(false)

  useEffect(() => {
    api.get<Wizard[]>('/wizards').then(r => setWizards(r.data)).catch(() => {})
  }, [])

  async function runWizard(wizard: Wizard) {
    setSelected(wizard)
    setRunning(true)
    setDone(false)
    setSteps(wizard.steps.map(s => ({ id: s.id, title: s.title, status: 'pending' })))

    try {
      const { data } = await api.post<{ run_id: string }>('/wizard/run', { wizard: wizard.name })
      const runId = data.run_id

      const origin = BASE.replace(/\/api$/, '')
      const es = new EventSource(`${origin}/api/wizard/run/${runId}/stream`)
      es.onmessage = (e) => {
        const event: StepEvent = JSON.parse(e.data)
        if (event.type === 'done') {
          setDone(true)
          setRunning(false)
          es.close()
        } else if (event.type === 'step_start') {
          setSteps(prev => prev.map(s =>
            s.id === event.step ? { ...s, status: 'running' } : s
          ))
        } else if (event.type === 'step_done') {
          setSteps(prev => prev.map(s =>
            s.id === event.step ? { ...s, status: 'done', result: event.result } : s
          ))
        } else if (event.type === 'step_error') {
          setSteps(prev => prev.map(s =>
            s.id === event.step ? { ...s, status: 'error', error: event.message } : s
          ))
        }
      }
      es.onerror = () => { setRunning(false); es.close() }
    } catch {
      setRunning(false)
    }
  }

  return (
    <div className="flex flex-col h-full">
      <div className="p-4 border-b border-border">
        <h2 className="text-lg font-semibold text-foreground">Wizards</h2>
        <p className="text-sm text-muted mt-1">Automated multi-step workflows</p>
      </div>

      {!selected ? (
        <div className="flex-1 overflow-auto p-4 space-y-3">
          {wizards.length === 0 && (
            <p className="text-sm text-muted">No wizards available. Install modules to enable wizards.</p>
          )}
          {wizards.map(w => (
            <div key={w.name} className="border border-border rounded-lg p-4 bg-surface">
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <h3 className="font-medium text-foreground">{w.title || w.name}</h3>
                  <p className="text-sm text-muted mt-1">{w.description}</p>
                  <div className="flex gap-1 mt-2 flex-wrap">
                    {w.requires.map(r => (
                      <span key={r} className="text-xs bg-surface-active border border-border rounded px-2 py-0.5 text-muted">{r}</span>
                    ))}
                  </div>
                </div>
                <button
                  onClick={() => runWizard(w)}
                  className="shrink-0 px-3 py-1.5 bg-accent text-white rounded text-sm font-medium hover:bg-accent-hover transition-colors"
                >
                  Run
                </button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="flex-1 overflow-auto p-4">
          <button
            onClick={() => { setSelected(null); setSteps([]); setDone(false) }}
            className="text-sm text-accent hover:underline mb-4 flex items-center gap-1"
          >
            ← Back to wizards
          </button>
          <h3 className="font-semibold text-foreground mb-4">{selected.title}</h3>
          <div className="space-y-3">
            {steps.map(step => (
              <div key={step.id} className={`border rounded-lg p-3 ${
                step.status === 'running' ? 'border-accent bg-surface' :
                step.status === 'done'    ? 'border-green-500/30 bg-surface' :
                step.status === 'error'   ? 'border-red-500/30 bg-surface' :
                                            'border-border bg-surface'
              }`}>
                <div className="flex items-center gap-2">
                  <span className={`w-2 h-2 rounded-full shrink-0 ${
                    step.status === 'running' ? 'bg-accent animate-pulse' :
                    step.status === 'done'    ? 'bg-green-500' :
                    step.status === 'error'   ? 'bg-red-500' :
                                                'bg-muted'
                  }`} />
                  <span className="text-sm font-medium text-foreground">{step.title || step.id}</span>
                  <span className="text-xs text-muted ml-auto capitalize">{step.status}</span>
                </div>
                {step.result && (
                  <pre className="mt-2 text-xs text-muted bg-surface-active rounded p-2 overflow-auto max-h-32 whitespace-pre-wrap">{step.result}</pre>
                )}
                {step.error && (
                  <p className="mt-2 text-xs text-red-400">{step.error}</p>
                )}
              </div>
            ))}
          </div>
          {done && (
            <div className="mt-4 p-3 border border-green-500/30 bg-surface rounded-lg text-sm text-green-500">
              Wizard completed successfully.
            </div>
          )}
        </div>
      )}
    </div>
  )
}
