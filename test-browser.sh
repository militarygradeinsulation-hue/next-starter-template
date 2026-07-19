#!/bin/bash

# AI Web Browser Test Script
# This script tests the browser automation API

echo "🤖 AI Web Browser - Test Script"
echo "================================"
echo ""

# Check if server is running
echo "📡 Checking server status..."
STATUS=$(curl -s http://localhost:3000/api/browser)
echo "$STATUS" | jq .
echo ""

# Test command 1: Google search
echo "🔍 Test 1: Search Google for AI news"
echo "------------------------------------"
curl -s -X POST http://localhost:3000/api/browser \
  -H "Content-Type: application/json" \
  -d '{"command":"Go to google.com and search for AI news"}' \
  | jq '{demoMode, currentUrl, steps: [.steps[] | {action, result}]}'
echo ""

# Test command 2: GitHub search
echo "🔍 Test 2: Search GitHub"
echo "------------------------------------"
curl -s -X POST http://localhost:3000/api/browser \
  -H "Content-Type: application/json" \
  -d '{"command":"Go to github.com and search for next.js"}' \
  | jq '{demoMode, currentUrl, steps: [.steps[] | {action, result}]}'
echo ""

# Test command 3: Hacker News
echo "🔍 Test 3: Visit Hacker News"
echo "------------------------------------"
curl -s -X POST http://localhost:3000/api/browser \
  -H "Content-Type: application/json" \
  -d '{"command":"Go to news.ycombinator.com"}' \
  | jq '{demoMode, currentUrl, steps: [.steps[] | {action, result}]}'
echo ""

echo "✅ All tests completed!"
echo ""
echo "📱 Open in browser: http://localhost:3000"
