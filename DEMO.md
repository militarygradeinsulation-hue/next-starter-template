# 🤖 AI Web Browser - Demo Guide

## ✨ Demo Mode is Active!

The application is running in **Demo Mode** which works immediately without any API keys or external dependencies.

## 🚀 Quick Start

### 1. Server is Already Running
```
http://localhost:3000
```

### 2. Open in Your Browser
Just click or paste the URL above into any browser.

### 3. Try These Commands

**Quick Actions (click the buttons):**
- Visit Hacker News
- Search GitHub
- Wikipedia Search

**Or type your own commands:**
```
Go to google.com and search for AI news
Navigate to github.com and search for next.js
Go to wikipedia.org and search for artificial intelligence
Visit news.ycombinator.com
```

## 🎭 What's Demo Mode?

Demo Mode uses **mock responses** that simulate browser automation:
- ✅ Full UI with all features
- ✅ Realistic browser actions (navigate, click, type, screenshot)
- ✅ Mock screenshots of websites
- ✅ Activity logging
- ✅ No API keys needed
- ✅ No Playwright installation needed
- ✅ Works immediately!

## 🔄 Test from Command Line

Run the test script:
```bash
./test-browser.sh
```

Or test individual commands:
```bash
curl -X POST http://localhost:3000/api/browser \
  -H "Content-Type: application/json" \
  -d '{"command":"Go to google.com"}'
```

## 🎯 Upgrade to Full AI Mode

To enable real AI-powered browser control:

1. **Add your Anthropic API key:**
   ```bash
   echo "ANTHROPIC_API_KEY=sk-ant-your-key-here" >> .env.local
   ```

2. **Install Playwright browsers:**
   ```bash
   npx playwright install chromium
   ```

3. **Restart the server:**
   ```bash
   npm run dev
   ```

The application will automatically switch to AI mode when it detects the API key!

## 📊 Features in Demo Mode

| Feature | Demo Mode | AI Mode |
|---------|-----------|---------|
| Web UI | ✅ | ✅ |
| Command Input | ✅ | ✅ |
| Browser Actions | 🎭 Simulated | ✅ Real |
| Screenshots | 🎭 Mock SVG | ✅ Real |
| Activity Logs | ✅ | ✅ |
| AI Command Parsing | 🎭 Pattern matching | ✅ Claude AI |
| Browser Control | ❌ | ✅ Playwright |

## 🧪 Example Interactions

### Demo Mode Output
```json
{
  "success": true,
  "demoMode": true,
  "currentUrl": "https://google.com",
  "steps": [
    {
      "action": "navigate (https://google.com)",
      "result": "Navigated to https://google.com",
      "screenshot": "base64-encoded-svg-screenshot"
    }
  ]
}
```

## 🎨 UI Features

- **Browser Viewport**: Shows screenshots of the browsed pages
- **Command Input**: Natural language command entry
- **Quick Actions**: Pre-configured command buttons
- **Activity Log**: Real-time action tracking
- **Demo Mode Badge**: Shows when running in demo mode

## 💡 Tips

1. **No Setup Required**: Demo mode works immediately
2. **Try Different Commands**: See how the system interprets different instructions
3. **View Screenshots**: Each action generates a mock screenshot
4. **API Access**: Test the REST API directly with curl
5. **Easy Upgrade**: Add API key anytime to enable full AI features

## 🔗 Resources

- **Web UI**: http://localhost:3000
- **API Endpoint**: http://localhost:3000/api/browser
- **Status Check**: http://localhost:3000/api/browser (GET)
- **Test Script**: `./test-browser.sh`

## 🎉 Enjoy!

The AI Web Browser is fully functional in demo mode. You can explore all the features, test commands, and see how it works before adding your API key for full AI-powered automation!
