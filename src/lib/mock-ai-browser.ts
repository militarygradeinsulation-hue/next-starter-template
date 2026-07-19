import { BrowserStep } from './ai-browser';

// Mock AI Browser for testing without API keys or Playwright
export class MockAIBrowser {
  private steps: BrowserStep[] = [];

  async executeCommand(userCommand: string): Promise<{
    steps: BrowserStep[];
    finalResult: string;
    currentUrl: string;
  }> {
    // Simulate AI processing delay
    await new Promise(resolve => setTimeout(resolve, 1000));

    const steps: BrowserStep[] = [];
    let currentUrl = 'about:blank';

    // Parse common commands and simulate actions
    const lowerCommand = userCommand.toLowerCase();

    if (lowerCommand.includes('google.com') || lowerCommand.includes('google')) {
      steps.push({
        action: 'navigate (https://google.com)',
        result: 'Navigated to https://google.com',
        screenshot: this.generateMockScreenshot('google')
      });
      currentUrl = 'https://google.com';

      if (lowerCommand.includes('search')) {
        const searchQuery = this.extractSearchQuery(userCommand);
        steps.push({
          action: 'type (input[name="q"])',
          result: `Typed "${searchQuery}" into search box`,
        });
        steps.push({
          action: 'click (input[type="submit"])',
          result: 'Clicked search button',
        });
        steps.push({
          action: 'wait (2000ms)',
          result: 'Waited for results to load',
        });
        steps.push({
          action: 'screenshot',
          result: 'Captured search results',
          screenshot: this.generateMockScreenshot('search-results')
        });
        currentUrl = `https://google.com/search?q=${encodeURIComponent(searchQuery)}`;
      }
    } else if (lowerCommand.includes('github.com') || lowerCommand.includes('github')) {
      steps.push({
        action: 'navigate (https://github.com)',
        result: 'Navigated to https://github.com',
        screenshot: this.generateMockScreenshot('github')
      });
      currentUrl = 'https://github.com';

      if (lowerCommand.includes('search')) {
        const searchQuery = this.extractSearchQuery(userCommand);
        steps.push({
          action: 'type (input[name="q"])',
          result: `Typed "${searchQuery}" into search box`,
        });
        steps.push({
          action: 'click (button[type="submit"])',
          result: 'Clicked search button',
        });
        steps.push({
          action: 'screenshot',
          result: 'Captured search results',
          screenshot: this.generateMockScreenshot('github-search')
        });
        currentUrl = `https://github.com/search?q=${encodeURIComponent(searchQuery)}`;
      }
    } else if (lowerCommand.includes('news.ycombinator.com') || lowerCommand.includes('hacker news')) {
      steps.push({
        action: 'navigate (https://news.ycombinator.com)',
        result: 'Navigated to Hacker News',
        screenshot: this.generateMockScreenshot('hackernews')
      });
      currentUrl = 'https://news.ycombinator.com';
    } else if (lowerCommand.includes('wikipedia.org') || lowerCommand.includes('wikipedia')) {
      steps.push({
        action: 'navigate (https://wikipedia.org)',
        result: 'Navigated to Wikipedia',
        screenshot: this.generateMockScreenshot('wikipedia')
      });
      currentUrl = 'https://wikipedia.org';

      if (lowerCommand.includes('search')) {
        const searchQuery = this.extractSearchQuery(userCommand);
        steps.push({
          action: 'type (input[name="search"])',
          result: `Typed "${searchQuery}" into search box`,
        });
        steps.push({
          action: 'click (button[type="submit"])',
          result: 'Clicked search button',
        });
        steps.push({
          action: 'screenshot',
          result: 'Captured article',
          screenshot: this.generateMockScreenshot('wikipedia-article')
        });
        currentUrl = `https://en.wikipedia.org/wiki/${searchQuery.replace(/\s+/g, '_')}`;
      }
    } else {
      // Generic command handling
      steps.push({
        action: 'interpret command',
        result: `Processing: "${userCommand}"`,
      });
      steps.push({
        action: 'screenshot',
        result: 'Current state captured',
        screenshot: this.generateMockScreenshot('generic')
      });
    }

    return {
      steps,
      finalResult: `Successfully executed: "${userCommand}" (Demo Mode)`,
      currentUrl
    };
  }

  private extractSearchQuery(command: string): string {
    const searchMatch = command.match(/search (?:for |about )?(.+)/i);
    return searchMatch ? searchMatch[1].trim() : 'AI news';
  }

  private generateMockScreenshot(type: string): string {
    // Generate SVG screenshots for different page types
    const screenshots: Record<string, string> = {
      google: this.createGoogleMock(),
      'search-results': this.createSearchResultsMock(),
      github: this.createGitHubMock(),
      'github-search': this.createGitHubSearchMock(),
      hackernews: this.createHackerNewsMock(),
      wikipedia: this.createWikipediaMock(),
      'wikipedia-article': this.createWikipediaArticleMock(),
      generic: this.createGenericMock()
    };

    const svg = screenshots[type] || screenshots.generic;
    return Buffer.from(svg).toString('base64');
  }

  private createGoogleMock(): string {
    return `<svg width="1280" height="720" xmlns="http://www.w3.org/2000/svg">
      <rect width="1280" height="720" fill="#fff"/>
      <text x="640" y="280" font-family="Arial" font-size="80" fill="#4285f4" text-anchor="middle">Google</text>
      <rect x="340" y="320" width="600" height="50" rx="25" fill="#fff" stroke="#ddd" stroke-width="2"/>
      <text x="640" y="352" font-family="Arial" font-size="16" fill="#999" text-anchor="middle">Search Google or type a URL</text>
      <text x="640" y="420" font-family="Arial" font-size="14" fill="#666" text-anchor="middle">DEMO MODE - Mock Screenshot</text>
    </svg>`;
  }

  private createSearchResultsMock(): string {
    return `<svg width="1280" height="720" xmlns="http://www.w3.org/2000/svg">
      <rect width="1280" height="720" fill="#fff"/>
      <text x="200" y="80" font-family="Arial" font-size="24" fill="#4285f4">Google</text>
      <rect x="200" y="100" width="600" height="40" rx="20" fill="#fff" stroke="#ddd" stroke-width="2"/>
      <rect x="200" y="170" width="700" height="80" fill="#f8f9fa" rx="8"/>
      <text x="220" y="200" font-family="Arial" font-size="18" fill="#1a0dab">Search Result #1</text>
      <text x="220" y="230" font-family="Arial" font-size="14" fill="#006621">www.example.com</text>
      <rect x="200" y="270" width="700" height="80" fill="#f8f9fa" rx="8"/>
      <text x="220" y="300" font-family="Arial" font-size="18" fill="#1a0dab">Search Result #2</text>
      <text x="640" y="680" font-family="Arial" font-size="12" fill="#999" text-anchor="middle">DEMO MODE</text>
    </svg>`;
  }

  private createGitHubMock(): string {
    return `<svg width="1280" height="720" xmlns="http://www.w3.org/2000/svg">
      <rect width="1280" height="720" fill="#0d1117"/>
      <rect width="1280" height="60" fill="#161b22"/>
      <text x="100" y="38" font-family="Arial" font-size="24" fill="#fff">GitHub</text>
      <rect x="400" y="15" width="400" height="30" rx="6" fill="#0d1117" stroke="#30363d" stroke-width="1"/>
      <text x="640" y="300" font-family="Arial" font-size="32" fill="#c9d1d9" text-anchor="middle">Where the world builds software</text>
      <text x="640" y="680" font-family="Arial" font-size="12" fill="#8b949e" text-anchor="middle">DEMO MODE</text>
    </svg>`;
  }

  private createGitHubSearchMock(): string {
    return `<svg width="1280" height="720" xmlns="http://www.w3.org/2000/svg">
      <rect width="1280" height="720" fill="#0d1117"/>
      <rect width="1280" height="60" fill="#161b22"/>
      <text x="100" y="38" font-family="Arial" font-size="24" fill="#fff">GitHub</text>
      <rect x="200" y="120" width="800" height="100" fill="#161b22" rx="8"/>
      <text x="220" y="155" font-family="Arial" font-size="18" fill="#58a6ff">Repository: example/project</text>
      <text x="220" y="185" font-family="Arial" font-size="14" fill="#8b949e">A sample project repository</text>
      <rect x="200" y="240" width="800" height="100" fill="#161b22" rx="8"/>
      <text x="220" y="275" font-family="Arial" font-size="18" fill="#58a6ff">Repository: another/repo</text>
      <text x="640" y="680" font-family="Arial" font-size="12" fill="#8b949e" text-anchor="middle">DEMO MODE</text>
    </svg>`;
  }

  private createHackerNewsMock(): string {
    return `<svg width="1280" height="720" xmlns="http://www.w3.org/2000/svg">
      <rect width="1280" height="720" fill="#f6f6ef"/>
      <rect width="1280" height="40" fill="#ff6600"/>
      <text x="20" y="28" font-family="Verdana" font-size="16" fill="#fff" font-weight="bold">Hacker News</text>
      <text x="200" y="100" font-family="Verdana" font-size="12" fill="#000">1. Interesting Tech Article (example.com)</text>
      <text x="200" y="140" font-family="Verdana" font-size="12" fill="#000">2. Show HN: I built something cool (github.com)</text>
      <text x="200" y="180" font-family="Verdana" font-size="12" fill="#000">3. Ask HN: How do I learn X? (news.ycombinator.com)</text>
      <text x="640" y="680" font-family="Arial" font-size="12" fill="#999" text-anchor="middle">DEMO MODE</text>
    </svg>`;
  }

  private createWikipediaMock(): string {
    return `<svg width="1280" height="720" xmlns="http://www.w3.org/2000/svg">
      <rect width="1280" height="720" fill="#fff"/>
      <text x="200" y="80" font-family="Georgia" font-size="32" fill="#000">Wikipedia</text>
      <text x="200" y="120" font-family="Georgia" font-size="16" fill="#666">The Free Encyclopedia</text>
      <rect x="340" y="280" width="600" height="50" rx="8" fill="#fff" stroke="#a2a9b1" stroke-width="2"/>
      <text x="640" y="312" font-family="Arial" font-size="16" fill="#999" text-anchor="middle">Search Wikipedia</text>
      <text x="640" y="680" font-family="Arial" font-size="12" fill="#999" text-anchor="middle">DEMO MODE</text>
    </svg>`;
  }

  private createWikipediaArticleMock(): string {
    return `<svg width="1280" height="720" xmlns="http://www.w3.org/2000/svg">
      <rect width="1280" height="720" fill="#fff"/>
      <text x="200" y="60" font-family="Georgia" font-size="24" fill="#000">Wikipedia</text>
      <text x="200" y="140" font-family="Georgia" font-size="28" fill="#000" font-weight="bold">Article Title</text>
      <text x="200" y="190" font-family="Georgia" font-size="16" fill="#333">This is a sample Wikipedia article about the topic.</text>
      <text x="200" y="220" font-family="Georgia" font-size="16" fill="#333">It contains informative content and references.</text>
      <rect x="900" y="140" width="250" height="300" fill="#f8f9fa" stroke="#a2a9b1" stroke-width="1"/>
      <text x="1025" y="170" font-family="Arial" font-size="12" fill="#333" text-anchor="middle">Info Box</text>
      <text x="640" y="680" font-family="Arial" font-size="12" fill="#999" text-anchor="middle">DEMO MODE</text>
    </svg>`;
  }

  private createGenericMock(): string {
    return `<svg width="1280" height="720" xmlns="http://www.w3.org/2000/svg">
      <rect width="1280" height="720" fill="#f5f5f5"/>
      <rect x="340" y="260" width="600" height="200" fill="#fff" stroke="#ddd" stroke-width="2" rx="8"/>
      <text x="640" y="340" font-family="Arial" font-size="24" fill="#333" text-anchor="middle">Browser View</text>
      <text x="640" y="380" font-family="Arial" font-size="16" fill="#666" text-anchor="middle">Command executed successfully</text>
      <text x="640" y="680" font-family="Arial" font-size="12" fill="#999" text-anchor="middle">DEMO MODE - Mock Screenshot</text>
    </svg>`;
  }
}
