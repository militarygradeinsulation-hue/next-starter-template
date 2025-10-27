import { NextRequest, NextResponse } from 'next/server';
import { AIBrowser } from '@/lib/ai-browser';

// Store browser instances (in production, use Redis or similar)
const browserSessions = new Map<string, AIBrowser>();

function getOrCreateBrowser(sessionId: string): AIBrowser {
  let browser = browserSessions.get(sessionId);

  if (!browser) {
    const apiKey = process.env.ANTHROPIC_API_KEY;
    if (!apiKey) {
      throw new Error('ANTHROPIC_API_KEY not configured');
    }
    browser = new AIBrowser(apiKey);
    browserSessions.set(sessionId, browser);

    // Clean up after 30 minutes of inactivity
    setTimeout(async () => {
      const b = browserSessions.get(sessionId);
      if (b) {
        await b.close();
        browserSessions.delete(sessionId);
      }
    }, 30 * 60 * 1000);
  }

  return browser;
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json() as { command?: string; sessionId?: string };
    const { command, sessionId = 'default' } = body;

    if (!command) {
      return NextResponse.json(
        { error: 'Command is required' },
        { status: 400 }
      );
    }

    const browser = getOrCreateBrowser(sessionId);
    const result = await browser.executeCommand(command);

    return NextResponse.json({
      success: true,
      ...result,
    });
  } catch (error) {
    console.error('Browser automation error:', error);
    return NextResponse.json(
      {
        error: error instanceof Error ? error.message : 'Unknown error occurred',
        success: false
      },
      { status: 500 }
    );
  }
}

export async function GET(request: NextRequest) {
  try {
    const sessionId = request.nextUrl.searchParams.get('sessionId') || 'default';
    const browser = browserSessions.get(sessionId);

    if (!browser) {
      return NextResponse.json(
        { error: 'No active browser session found' },
        { status: 404 }
      );
    }

    const state = await browser.getCurrentState();

    return NextResponse.json({
      success: true,
      ...state,
    });
  } catch (error) {
    console.error('Get browser state error:', error);
    return NextResponse.json(
      {
        error: error instanceof Error ? error.message : 'Unknown error occurred',
        success: false
      },
      { status: 500 }
    );
  }
}

export async function DELETE(request: NextRequest) {
  try {
    const sessionId = request.nextUrl.searchParams.get('sessionId') || 'default';
    const browser = browserSessions.get(sessionId);

    if (browser) {
      await browser.close();
      browserSessions.delete(sessionId);
    }

    return NextResponse.json({
      success: true,
      message: 'Browser session closed',
    });
  } catch (error) {
    console.error('Close browser error:', error);
    return NextResponse.json(
      {
        error: error instanceof Error ? error.message : 'Unknown error occurred',
        success: false
      },
      { status: 500 }
    );
  }
}
