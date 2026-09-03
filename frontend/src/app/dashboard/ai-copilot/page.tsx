/**
 * The AI Copilot page - linked from Sidebar.tsx's nav since it was written, but never actually
 * built until now. Caught while writing the local-verification checklist: sending someone to
 * click "AI Copilot" in the sidebar and hit a 404 would have undermined the exact thing this
 * checklist is supposed to verify. Calls the real, already-built backend pipeline
 * (POST /ai/query -> app.ai.copilot_service.answer_query -> the intent router, tested in
 * tests_pure/test_intent_router.py) - this page has never actually been run (no npm install, no
 * live LLM in this sandbox), so treat a first real run here as genuinely first-time verification,
 * not a formality. Sidebar/DashboardHeader now come from app/dashboard/layout.tsx, not rendered
 * inline here.
 */
"use client";

import { useState } from "react";
import { aiCopilotApi, type CopilotQueryResponse } from "@/lib/dashboard-api";

const EXAMPLE_QUESTIONS = [
  "What is our total spend by supplier?",
  "Which suppliers are in the top tier by cumulative spend?",
  "Are we paying inconsistent prices for any item?",
  "Which contracts are expiring soon?",
];

export default function AiCopilotPage() {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<CopilotQueryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!question.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const response = await aiCopilotApi.query(question);
      setResult(response);
    } catch (err) {
      // Expected on a first local run without LLM_API_KEY configured - this is the honest
      // failure mode, not a bug in this page. See docs/runbook.md.
      setError(err instanceof Error ? err.message : "The copilot could not answer that question");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto w-full max-w-3xl flex-1 p-6">
      <h1 className="text-slate-100 font-semibold text-lg">AI Procurement Copilot</h1>
          <p className="mt-1 text-slate-400 text-xs">
            Ask a question about spend, pricing, rebates, or contracts. Every answer is grounded
            in a deterministic backend calculation - the model classifies your question into one
            of a fixed set of pre-approved queries and never generates or runs one itself.
          </p>

          <form onSubmit={handleSubmit} className="mt-6">
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="e.g. What is our total spend by supplier?"
              rows={3}
              className="w-full rounded-xl border border-[#1F2438] bg-[#131625]/90 p-4 text-sm text-slate-200 placeholder:text-slate-500 shadow-lg backdrop-blur-sm focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
            <div className="mt-3 flex items-center justify-between">
              <div className="flex flex-wrap gap-2">
                {EXAMPLE_QUESTIONS.map((q) => (
                  <button
                    key={q}
                    type="button"
                    onClick={() => setQuestion(q)}
                    className="rounded-full border border-[#1F2438] px-3 py-1 text-xs text-slate-400 hover:border-indigo-500/40 hover:text-indigo-400"
                  >
                    {q}
                  </button>
                ))}
              </div>
              <button
                type="submit"
                disabled={loading || !question.trim()}
                className="rounded-md bg-indigo-500 px-4 py-2 text-sm font-medium text-white shadow-[0_0_20px_rgba(99,102,241,0.25)] disabled:opacity-40"
              >
                {loading ? "Thinking…" : "Ask"}
              </button>
            </div>
          </form>

          {error && (
            <div className="mt-6 rounded-xl border border-rose-500/20 bg-rose-500/10 p-4 text-sm text-rose-400">
              {error}
            </div>
          )}

          {result && (
            <div className="mt-6 space-y-4">
              <div className="rounded-xl border border-[#1F2438] bg-[#131625]/90 p-5 shadow-lg backdrop-blur-sm">
                <p className="text-xs text-slate-500">
                  Classified as: <span className="text-indigo-400">{result.intent}</span>
                </p>
                <p className="mt-2 text-sm text-slate-200 whitespace-pre-wrap">{result.summary}</p>
              </div>
              <details className="rounded-xl border border-[#1F2438] bg-[#131625]/60 p-4">
                <summary className="cursor-pointer text-xs text-slate-500">Structured data behind this answer</summary>
                <pre className="mt-2 overflow-auto text-xs text-slate-400">
                  {JSON.stringify(result.structured_result, null, 2)}
                </pre>
              </details>
            </div>
          )}
        </main>
  );
}
