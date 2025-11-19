import { test, expect } from '@playwright/test'

test.describe('Chat experience', () => {
  test('sends a message and renders assistant reply with mocked backend', async ({ page }) => {
    await page.route('**/chat', async (route) => {
      const request = await route.request().postDataJSON()
      const lastMessage = request.messages.at(-1)?.content ?? ''
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          response: { role: 'assistant', content: `Echo: ${lastMessage}` },
          actions: [
            { type: 'decision', message: 'mocked' }
          ],
          memory: { sessionId: request.sessionId }
        })
      })
    })

    await page.route('**/events*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: 'event: ready\ndata: {"status":"ready"}\n\n'
      })
    })

    await page.goto('/')

    const textarea = page.getByRole('textbox')
    await textarea.fill('Hello planner')
    await page.getByRole('button', { name: /send/i }).click()

    await expect(page.getByText('Echo: Hello planner')).toBeVisible()
  })

  test('uses /calc quick action without hitting /chat', async ({ page }) => {
    let chatCalled = false

    await page.route('**/chat', async (route) => {
      chatCalled = true
      await route.fulfill({ status: 500 })
    })

    await page.route('**/calc*', async (route) => {
      const url = new URL(route.request().url())
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          expression: url.searchParams.get('query'),
          result: 15
        })
      })
    })

    await page.goto('/')
    await page.getByRole('textbox').fill('/calc 5+10')
    await page.getByRole('button', { name: /send/i }).click()

    await expect(page.getByText(/calculated \*\*5\+10\*\*/i)).toBeVisible()
    expect(chatCalled).toBe(false)
  })

  test('uses /products quick action and surfaces tool activity', async ({ page }) => {
    await page.route('**/products*', async (route) => {
      const url = new URL(route.request().url())
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          query: url.searchParams.get('query'),
          topK: [
            { title: 'Steel Bottle', score: 0.92 },
            { title: 'Glass Tumbler', score: 0.85 }
          ],
          summary: 'Steel Bottle and Glass Tumbler are in stock.'
        })
      })
    })

    await page.route('**/events*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: 'event: ready\ndata: {"status":"ready"}\n\n'
      })
    })

    await page.goto('/')
    await page.getByRole('textbox').fill('/products bottle')
    await page.getByRole('button', { name: /send/i }).click()

    await expect(page.getByText(/steel bottle and glass tumbler/i)).toBeVisible()
    await expect(page.getByText(/Product Search/)).toBeVisible()
  })

  test('uses /outlets quick action and formats outlet details', async ({ page }) => {
    await page.route('**/outlets*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          query: 'ss2 outlets',
          sql: 'SELECT * FROM outlets',
          params: {},
          rows: [
            {
              name: 'ZUS Coffee SS 2',
              city: 'Petaling Jaya',
              state: 'Selangor',
              address: '123 Jalan SS 2',
              open_time: '09:00',
              close_time: '21:00'
            }
          ]
        })
      })
    })

    await page.route('**/events*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: 'event: ready\ndata: {"status":"ready"}\n\n'
      })
    })

    await page.goto('/')
    await page.getByRole('textbox').fill('/outlets ss2 outlets')
    await page.getByRole('button', { name: /send/i }).click()

    await expect(page.getByText(/zus coffee ss 2/i)).toBeVisible()
    await expect(page.getByText(/Petaling Jaya/i)).toBeVisible()
  })

  test('shows validation guidance when quick action lacks arguments', async ({ page }) => {
    await page.route('**/events*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: 'event: ready\ndata: {"status":"ready"}\n\n'
      })
    })

    await page.goto('/')
    await page.getByRole('textbox').fill('/calc')
    await page.getByRole('button', { name: /send/i }).click()

    await expect(page.getByText(/provide an expression after \/calc/i).first()).toBeVisible()
  })

  test('recovers gracefully when /chat returns an error', async ({ page }) => {
    await page.route('**/chat', async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'LLM backend down' })
      })
    })

    await page.route('**/events*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: 'event: ready\ndata: {"status":"ready"}\n\n'
      })
    })

    await page.goto('/')
    await page.getByRole('textbox').fill('Hello?')
    await page.getByRole('button', { name: /send/i }).click()

    await expect(
      page.getByText(/assistant services are temporarily unavailable/i).first()
    ).toBeVisible()
  })
})

