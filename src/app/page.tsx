'use client';

import { useState } from 'react';

interface BrowserStep {
  action: string;
  result: string;
  screenshot?: string;
}

interface BrowserResponse {
  success: boolean;
  steps: BrowserStep[];
  finalResult: string;
  currentUrl: string;
  error?: string;
  demoMode?: boolean;
}

export default function Home() {
  const [command, setCommand] = useState('');
  const [loading, setLoading] = useState(false);
  const [response, setResponse] = useState<BrowserResponse | null>(null);
  const [history, setHistory] = useState<Array<{ command: string; response: BrowserResponse }>>([]);
  const [currentScreenshot, setCurrentScreenshot] = useState<string | null>(null);
  const [demoMode, setDemoMode] = useState<boolean>(false);

  const executeCommand = async () => {
    if (!command.trim()) return;

    setLoading(true);
    try {
      const res = await fetch('/api/browser', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ command }),
      });

      const data: BrowserResponse = await res.json();

      if (data.success) {
        setResponse(data);
        setHistory(prev => [...prev, { command, response: data }]);
        setDemoMode(data.demoMode || false);

        // Find the last screenshot
        const lastScreenshot = data.steps
          .slice()
          .reverse()
          .find(step => step.screenshot)?.screenshot;

        if (lastScreenshot) {
          setCurrentScreenshot(lastScreenshot);
        }
      } else {
        setResponse(data);
        setDemoMode(data.demoMode || false);
      }

      setCommand('');
    } catch (error) {
      setResponse({
        success: false,
        steps: [],
        finalResult: '',
        currentUrl: '',
        error: error instanceof Error ? error.message : 'Failed to execute command',
      });
    } finally {
      setLoading(false);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      executeCommand();
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 text-white">
      {/* Header */}
      <header className="border-b border-slate-700 bg-slate-900/50 backdrop-blur-sm sticky top-0 z-10">
        <div className="container mx-auto px-4 py-4">
          <h1 className="text-2xl font-bold bg-gradient-to-r from-blue-400 to-purple-500 bg-clip-text text-transparent">
            AI Web Browser
          </h1>
          <p className="text-slate-400 text-sm mt-1">
            Control a browser with natural language commands powered by Claude AI
          </p>
          {demoMode && (
            <div className="mt-2 text-xs bg-yellow-900/30 border border-yellow-700 rounded px-3 py-1.5 text-yellow-200 inline-block">
              🎭 Demo Mode - Add ANTHROPIC_API_KEY to .env.local for real AI
            </div>
          )}
        </div>
      </header>

      <div className="container mx-auto px-4 py-6">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Left Panel - Browser Viewport */}
          <div className="space-y-4">
            <div className="bg-slate-800/50 rounded-lg border border-slate-700 overflow-hidden">
              <div className="bg-slate-900/50 px-4 py-2 border-b border-slate-700">
                <h2 className="text-sm font-semibold text-slate-300">Browser Viewport</h2>
                {response?.currentUrl && (
                  <p className="text-xs text-slate-500 mt-1 truncate">{response.currentUrl}</p>
                )}
              </div>
              <div className="aspect-video bg-slate-900 flex items-center justify-center">
                {currentScreenshot ? (
                  <img
                    src={`data:image/png;base64,${currentScreenshot}`}
                    alt="Browser screenshot"
                    className="w-full h-full object-contain"
                  />
                ) : (
                  <div className="text-center text-slate-500">
                    <svg
                      className="w-16 h-16 mx-auto mb-2 opacity-50"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
                      />
                    </svg>
                    <p>No browser session active</p>
                    <p className="text-xs mt-2">Send a command to start browsing</p>
                  </div>
                )}
              </div>
            </div>

            {/* Command Input */}
            <div className="bg-slate-800/50 rounded-lg border border-slate-700 p-4">
              <label htmlFor="command" className="block text-sm font-semibold text-slate-300 mb-2">
                Enter Command
              </label>
              <div className="flex gap-2">
                <input
                  id="command"
                  type="text"
                  value={command}
                  onChange={(e) => setCommand(e.target.value)}
                  onKeyPress={handleKeyPress}
                  placeholder="e.g., Go to google.com and search for AI news"
                  className="flex-1 bg-slate-900 border border-slate-600 rounded-lg px-4 py-3 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  disabled={loading}
                />
                <button
                  onClick={executeCommand}
                  disabled={loading || !command.trim()}
                  className="bg-blue-600 hover:bg-blue-700 disabled:bg-slate-700 disabled:text-slate-500 disabled:cursor-not-allowed px-6 py-3 rounded-lg font-medium transition-colors"
                >
                  {loading ? (
                    <span className="flex items-center gap-2">
                      <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24">
                        <circle
                          className="opacity-25"
                          cx="12"
                          cy="12"
                          r="10"
                          stroke="currentColor"
                          strokeWidth="4"
                          fill="none"
                        />
                        <path
                          className="opacity-75"
                          fill="currentColor"
                          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                        />
                      </svg>
                      Processing...
                    </span>
                  ) : (
                    'Execute'
                  )}
                </button>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  onClick={() => setCommand('Go to news.ycombinator.com')}
                  className="text-xs bg-slate-700 hover:bg-slate-600 px-3 py-1 rounded-full transition-colors"
                  disabled={loading}
                >
                  Visit Hacker News
                </button>
                <button
                  onClick={() => setCommand('Go to github.com and search for next.js')}
                  className="text-xs bg-slate-700 hover:bg-slate-600 px-3 py-1 rounded-full transition-colors"
                  disabled={loading}
                >
                  Search GitHub
                </button>
                <button
                  onClick={() => setCommand('Go to wikipedia.org and search for artificial intelligence')}
                  className="text-xs bg-slate-700 hover:bg-slate-600 px-3 py-1 rounded-full transition-colors"
                  disabled={loading}
                >
                  Wikipedia Search
                </button>
              </div>
            </div>
          </div>

          {/* Right Panel - Activity Log */}
          <div className="space-y-4">
            <div className="bg-slate-800/50 rounded-lg border border-slate-700 max-h-[calc(100vh-200px)] flex flex-col">
              <div className="bg-slate-900/50 px-4 py-2 border-b border-slate-700 flex-shrink-0">
                <h2 className="text-sm font-semibold text-slate-300">Activity Log</h2>
              </div>
              <div className="flex-1 overflow-y-auto p-4 space-y-4">
                {history.length === 0 ? (
                  <div className="text-center text-slate-500 py-8">
                    <p>No activity yet</p>
                    <p className="text-xs mt-2">Your browser actions will appear here</p>
                  </div>
                ) : (
                  history.map((item, idx) => (
                    <div key={idx} className="space-y-2">
                      <div className="bg-slate-900/50 rounded-lg p-3 border border-slate-700">
                        <div className="flex items-start gap-2 mb-2">
                          <svg
                            className="w-5 h-5 text-blue-400 flex-shrink-0 mt-0.5"
                            fill="none"
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                          >
                            <path
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              strokeWidth={2}
                              d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"
                            />
                          </svg>
                          <div className="flex-1">
                            <p className="text-sm font-medium text-slate-200">{item.command}</p>
                            <p className="text-xs text-slate-500 mt-1">Command #{idx + 1}</p>
                          </div>
                        </div>

                        {item.response.steps.length > 0 && (
                          <div className="mt-3 space-y-1">
                            {item.response.steps.map((step, stepIdx) => (
                              <div
                                key={stepIdx}
                                className="text-xs bg-slate-800 rounded px-2 py-1.5 border border-slate-700"
                              >
                                <span className="text-blue-400 font-mono">{step.action}</span>
                                <span className="text-slate-400 ml-2">→ {step.result}</span>
                              </div>
                            ))}
                          </div>
                        )}

                        {item.response.finalResult && (
                          <div className="mt-2 text-xs text-green-400 bg-green-950/30 border border-green-900 rounded px-2 py-1.5">
                            {item.response.finalResult}
                          </div>
                        )}

                        {item.response.error && (
                          <div className="mt-2 text-xs text-red-400 bg-red-950/30 border border-red-900 rounded px-2 py-1.5">
                            Error: {item.response.error}
                          </div>
                        )}
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
