import React, { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { Skeleton } from './Skeleton'

interface Report {
  id: string
  ext: string
  size: number
  created_at: string
}

export default function ReportViewer() {
  const [reports, setReports] = useState<Report[]>([])
  const [selected, setSelected] = useState<Report | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    loadReports()
  }, [])

  async function loadReports() {
    setLoading(true)
    try {
      const { data } = await api.get<Report[]>('/reports')
      setReports(data)
    } catch {
      // backend may not be running
    } finally {
      setLoading(false)
    }
  }

  function formatSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  }

  function formatDate(iso: string): string {
    try {
      return new Date(iso).toLocaleString()
    } catch {
      return iso
    }
  }

  const reportUrl = (r: Report) => `/api/report/${r.id}`

  return (
    <div className="flex flex-col h-full">
      <div className="p-4 border-b border-border flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-foreground">Reports</h2>
          <p className="text-sm text-muted mt-0.5">Generated analysis reports</p>
        </div>
        <button
          onClick={loadReports}
          className="text-sm text-accent hover:underline"
        >
          Refresh
        </button>
      </div>

      {selected ? (
        <div className="flex flex-col flex-1 min-h-0">
          <div className="flex items-center gap-3 p-3 border-b border-border bg-surface text-sm">
            <button onClick={() => setSelected(null)} className="text-accent hover:underline">
              &larr; Reports
            </button>
            <span className="text-muted">{selected.id}.{selected.ext}</span>
            <a
              href={reportUrl(selected)}
              download
              className="ml-auto text-accent hover:underline"
            >
              Download
            </a>
          </div>
          {selected.ext === 'html' ? (
            <iframe
              src={reportUrl(selected)}
              className="flex-1 w-full border-0 bg-white"
              title={`Report ${selected.id}`}
            />
          ) : selected.ext === 'json' ? (
            <iframe
              src={reportUrl(selected)}
              className="flex-1 w-full border-0"
              title={`Report ${selected.id}`}
            />
          ) : (
            <div className="flex-1 flex items-center justify-center text-muted">
              <div className="text-center">
                <p className="mb-3">PDF preview not available in-app.</p>
                <a href={reportUrl(selected)} download
                   className="text-accent hover:underline">
                  Download PDF
                </a>
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="flex-1 overflow-auto">
          {loading && (
            <div className="p-4 space-y-3">
              {[...Array(5)].map((_, i) => (
                <div key={i} className="flex gap-4 items-center w-full border-b border-border p-4">
                  <div className="flex-1 space-y-2">
                     <Skeleton className="h-4 w-1/3" />
                     <Skeleton className="h-3 w-1/4" />
                  </div>
                  <Skeleton className="h-4 w-12" />
                </div>
              ))}
            </div>
          )}
          {!loading && reports.length === 0 && (
            <div className="p-4 text-sm text-muted">
              No reports yet. Run a wizard or use the AI agent to generate reports.
            </div>
          )}
          {reports.map(r => (
            <button
              key={r.id}
              onClick={() => setSelected(r)}
              className="w-full flex items-center gap-3 p-4 border-b border-border hover:bg-surface text-left transition-colors"
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono uppercase bg-surface-active border border-border rounded px-1.5 py-0.5 text-muted">{r.ext}</span>
                  <span className="text-sm font-medium text-foreground font-mono">{r.id}</span>
                </div>
                <div className="text-xs text-muted mt-1">{formatDate(r.created_at)} &middot; {formatSize(r.size)}</div>
              </div>
              <span className="text-accent text-sm">View &rarr;</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
