# AI Web Browser

An intelligent web browser controlled by natural language commands, powered by Claude AI and Playwright.

[![Deploy to Cloudflare](https://deploy.workers.cloudflare.com/button)](https://deploy.workers.cloudflare.com/?url=https://github.com/cloudflare/templates/tree/main/next-starter-template)

## Features

- **Natural Language Control**: Tell the browser what to do in plain English
- **AI-Powered Navigation**: Claude AI interprets your commands and executes browser actions
- **Real-time Visualization**: See screenshots of the browser as it navigates
- **Action Logging**: Track every step the AI takes
- **Session Management**: Persistent browser sessions for multi-step tasks

## How It Works

1. **User Input**: You provide a natural language command (e.g., "Go to Google and search for AI news")
2. **AI Processing**: Claude AI breaks down your command into specific browser actions
3. **Browser Automation**: Playwright executes the actions (navigate, click, type, screenshot, etc.)
4. **Visual Feedback**: Screenshots and logs show you what's happening in real-time

## Tech Stack

- **Next.js 15**: React framework with App Router
- **Playwright**: Browser automation library
- **Anthropic Claude API**: AI command interpretation
- **TypeScript**: Type-safe development
- **Tailwind CSS**: Modern styling
- **Cloudflare Workers**: Serverless deployment platform

## Getting Started

### Prerequisites

- Node.js 18+ installed
- An Anthropic API key ([get one here](https://console.anthropic.com/))
- Playwright browsers installed

### Installation

1. Clone the repository and install dependencies:

```bash
npm install
```

2. Set up your environment variables:

```bash
cp .env.example .env.local
```

Edit `.env.local` and add your Anthropic API key:

```env
ANTHROPIC_API_KEY=your_api_key_here
```

3. Install Playwright browsers:

```bash
npx playwright install chromium
```

4. Run the development server:

```bash
npm run dev
```

5. Open [http://localhost:3000](http://localhost:3000) in your browser.

## Usage Examples

Try these commands with the AI browser:

- `Go to news.ycombinator.com`
- `Navigate to github.com and search for next.js`
- `Go to wikipedia.org and search for artificial intelligence`
- `Visit youtube.com and search for AI tutorials`
- `Go to reddit.com and browse the programming subreddit`

## API Endpoints

### POST /api/browser

Execute a browser command.

**Request:**
```json
{
  "command": "Go to google.com and search for AI",
  "sessionId": "optional-session-id"
}
```

**Response:**
```json
{
  "success": true,
  "steps": [
    {
      "action": "navigate (https://google.com)",
      "result": "Navigated to https://google.com",
      "screenshot": "base64-encoded-image"
    }
  ],
  "finalResult": "Task completed",
  "currentUrl": "https://google.com"
}
```

### GET /api/browser?sessionId=xxx

Get the current state of a browser session.

### DELETE /api/browser?sessionId=xxx

Close and cleanup a browser session.

## Architecture

```
┌─────────────┐
│   Frontend  │  (React/Next.js UI)
│   page.tsx  │
└──────┬──────┘
       │
       ├─ POST /api/browser
       │
┌──────▼──────────────┐
│   API Route         │
│   route.ts          │
└──────┬──────────────┘
       │
       ├─ AIBrowser.executeCommand()
       │
┌──────▼──────────────┐
│   AI Browser        │
│   ai-browser.ts     │
├─────────────────────┤
│ • Claude AI         │ (Interprets commands)
│ • Playwright        │ (Controls browser)
│ • Action Executor   │ (Runs browser tasks)
└─────────────────────┘
```

## Project Structure

```
src/
├── app/
│   ├── page.tsx              # Main UI component
│   ├── layout.tsx            # Root layout
│   ├── globals.css           # Global styles
│   └── api/
│       └── browser/
│           └── route.ts      # Browser automation API
└── lib/
    └── ai-browser.ts         # AI browser service
```

## Development

### Building for Production

```bash
npm run build
```

### Type Checking

```bash
npm run check
```

### Linting

```bash
npm run lint
```

## Deploying to Cloudflare Workers

This project is configured to deploy on Cloudflare Workers using OpenNext.

| Command                           | Action                                       |
| :-------------------------------- | :------------------------------------------- |
| `npm run build`                   | Build your production site                   |
| `npm run preview`                 | Preview your build locally, before deploying |
| `npm run build && npm run deploy` | Deploy your production site to Cloudflare    |
| `npm wrangler tail`               | View real-time logs for all Workers          |

**Note**: For Cloudflare Workers deployment, you may need to use Cloudflare's Browser Rendering API instead of Playwright, as Playwright requires a full Node.js environment with browser binaries.

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `ANTHROPIC_API_KEY` | Your Anthropic API key for Claude AI | Yes |

## Security Considerations

- Never commit your `.env.local` file with API keys
- API keys should be stored in environment variables
- In production, implement rate limiting and authentication
- Browser sessions have a 30-minute timeout by default
- Consider implementing request validation and sanitization

## Limitations

- Browser sessions are stored in memory (use Redis for production)
- Playwright requires a Node.js runtime (not compatible with edge runtimes out of the box)
- AI command interpretation depends on Claude API availability
- Browser automation may be blocked by some websites

## Troubleshooting

### "ANTHROPIC_API_KEY not configured" error

Make sure you've created a `.env.local` file with your API key.

### Playwright browser download fails

Run `npx playwright install chromium` manually to download browser binaries.

### Browser actions timing out

Some websites take longer to load. The AI may need to add wait actions between steps.

## Learn More

- [Next.js Documentation](https://nextjs.org/docs)
- [Playwright Documentation](https://playwright.dev/)
- [Anthropic API Documentation](https://docs.anthropic.com/)
- [Cloudflare Workers](https://developers.cloudflare.com/workers/)

## License

This project is based on the [Next.js Cloudflare template](https://github.com/cloudflare/templates/tree/main/next-starter-template).
