import Anthropic from '@anthropic-ai/sdk';
import { chromium, Browser, Page } from 'playwright';

export interface BrowserAction {
  type: 'navigate' | 'click' | 'type' | 'scroll' | 'screenshot' | 'extract' | 'wait';
  selector?: string;
  text?: string;
  url?: string;
  timeout?: number;
}

export interface BrowserStep {
  action: string;
  result: string;
  screenshot?: string;
}

export class AIBrowser {
  private browser: Browser | null = null;
  private page: Page | null = null;
  private anthropic: Anthropic;
  private conversationHistory: Array<{ role: 'user' | 'assistant'; content: string }> = [];

  constructor(apiKey: string) {
    this.anthropic = new Anthropic({ apiKey });
  }

  async initialize(): Promise<void> {
    if (!this.browser) {
      this.browser = await chromium.launch({
        headless: true,
      });
      this.page = await this.browser.newPage();
      await this.page.setViewportSize({ width: 1280, height: 720 });
    }
  }

  async close(): Promise<void> {
    if (this.page) {
      await this.page.close();
      this.page = null;
    }
    if (this.browser) {
      await this.browser.close();
      this.browser = null;
    }
  }

  async executeCommand(userCommand: string): Promise<{
    steps: BrowserStep[];
    finalResult: string;
    currentUrl: string;
  }> {
    await this.initialize();

    if (!this.page) {
      throw new Error('Browser page not initialized');
    }

    const steps: BrowserStep[] = [];

    // Get current page state
    const currentUrl = this.page.url();
    const pageTitle = await this.page.title();
    const pageContent = await this.page.evaluate(() => {
      // Get visible text content, limited to first 3000 chars
      const text = document.body.innerText;
      return text.substring(0, 3000);
    });

    // Ask Claude what actions to take
    const systemPrompt = `You are an AI that controls a web browser. The user will give you a task, and you need to break it down into specific browser actions.

Current browser state:
- URL: ${currentUrl || 'about:blank'}
- Page Title: ${pageTitle || 'New Tab'}
- Visible Content (first 3000 chars): ${pageContent}

Available actions:
1. navigate(url) - Navigate to a URL
2. click(selector) - Click an element (CSS selector)
3. type(selector, text) - Type text into an input field
4. scroll(direction) - Scroll up or down
5. screenshot() - Take a screenshot
6. extract(selector) - Extract text from element
7. wait(ms) - Wait for specified milliseconds

Respond with a JSON array of actions to perform. Each action should have:
- type: the action type
- selector: CSS selector (for click, type, extract)
- text: text to type (for type action)
- url: URL to navigate to (for navigate)
- timeout: milliseconds to wait (for wait)

Example response:
[
  {"type": "navigate", "url": "https://google.com"},
  {"type": "type", "selector": "input[name='q']", "text": "AI news"},
  {"type": "click", "selector": "input[type='submit']"},
  {"type": "wait", "timeout": 2000},
  {"type": "screenshot"}
]

Only respond with valid JSON array of actions, no other text.`;

    try {
      const response = await this.anthropic.messages.create({
        model: 'claude-3-5-sonnet-20241022',
        max_tokens: 2000,
        system: systemPrompt,
        messages: [
          ...this.conversationHistory,
          {
            role: 'user',
            content: userCommand,
          },
        ],
      });

      const content = response.content[0];
      if (content.type !== 'text') {
        throw new Error('Unexpected response type from Claude');
      }

      // Parse Claude's response
      let actions: BrowserAction[];
      try {
        // Extract JSON from response (Claude might wrap it in markdown)
        const jsonMatch = content.text.match(/\[[\s\S]*\]/);
        if (!jsonMatch) {
          throw new Error('No JSON array found in response');
        }
        actions = JSON.parse(jsonMatch[0]);
      } catch (parseError) {
        throw new Error(`Failed to parse actions from Claude: ${parseError}`);
      }

      // Execute each action
      for (const action of actions) {
        const step = await this.executeAction(action);
        steps.push(step);
      }

      // Update conversation history
      this.conversationHistory.push(
        { role: 'user', content: userCommand },
        { role: 'assistant', content: content.text }
      );

      // Keep conversation history manageable
      if (this.conversationHistory.length > 10) {
        this.conversationHistory = this.conversationHistory.slice(-10);
      }

      return {
        steps,
        finalResult: steps[steps.length - 1]?.result || 'Task completed',
        currentUrl: this.page.url(),
      };
    } catch (error) {
      throw new Error(`Failed to execute command: ${error}`);
    }
  }

  private async executeAction(action: BrowserAction): Promise<BrowserStep> {
    if (!this.page) {
      throw new Error('Browser page not initialized');
    }

    let result = '';
    let screenshot: string | undefined;

    try {
      switch (action.type) {
        case 'navigate':
          if (!action.url) throw new Error('URL required for navigate action');
          await this.page.goto(action.url, { waitUntil: 'networkidle' });
          result = `Navigated to ${action.url}`;
          break;

        case 'click':
          if (!action.selector) throw new Error('Selector required for click action');
          await this.page.click(action.selector);
          result = `Clicked element: ${action.selector}`;
          break;

        case 'type':
          if (!action.selector || !action.text) {
            throw new Error('Selector and text required for type action');
          }
          await this.page.fill(action.selector, action.text);
          result = `Typed "${action.text}" into ${action.selector}`;
          break;

        case 'scroll':
          await this.page.evaluate(() => {
            window.scrollBy(0, window.innerHeight);
          });
          result = 'Scrolled down';
          break;

        case 'screenshot':
          const buffer = await this.page.screenshot({ fullPage: false });
          screenshot = buffer.toString('base64');
          result = 'Screenshot captured';
          break;

        case 'extract':
          if (!action.selector) throw new Error('Selector required for extract action');
          const text = await this.page.textContent(action.selector);
          result = `Extracted text: ${text || '(empty)'}`;
          break;

        case 'wait':
          const timeout = action.timeout || 1000;
          await this.page.waitForTimeout(timeout);
          result = `Waited ${timeout}ms`;
          break;

        default:
          throw new Error(`Unknown action type: ${action.type}`);
      }
    } catch (error) {
      result = `Error: ${error}`;
    }

    return {
      action: `${action.type}${action.selector ? ` (${action.selector})` : ''}${action.url ? ` (${action.url})` : ''}`,
      result,
      screenshot,
    };
  }

  async getCurrentState(): Promise<{
    url: string;
    title: string;
    screenshot: string;
  }> {
    if (!this.page) {
      throw new Error('Browser not initialized');
    }

    const buffer = await this.page.screenshot({ fullPage: false });
    return {
      url: this.page.url(),
      title: await this.page.title(),
      screenshot: buffer.toString('base64'),
    };
  }

  resetConversation(): void {
    this.conversationHistory = [];
  }
}
