import { expect, type Page } from "@playwright/test";
import { test } from "./fixtures";

// ── Mock data ────────────────────────────────────────────────

const MOCK_DESK_RESPONSE = {
    trades: {
        pending: [
            {
                trade_id: "T-PEND-001",
                account_id: "ACC-001",
                status: "INTENDED",
                pair: "EURUSD",
                direction: "BUY",
                lot_size: 0.1,
                entry_price: 1.1,
                stop_loss: 1.095,
                take_profit: 1.11,
                created_at: "2025-01-01T00:00:00Z",
            },
        ],
        open: [
            {
                trade_id: "T-OPEN-001",
                account_id: "ACC-001",
                status: "OPEN",
                pair: "GBPUSD",
                direction: "SELL",
                lot_size: 0.2,
                entry_price: 1.25,
                stop_loss: 1.255,
                take_profit: 1.24,
                pnl: 15.5,
                opened_at: "2025-01-01T01:00:00Z",
            },
            {
                trade_id: "T-OPEN-002",
                account_id: "ACC-002",
                status: "OPEN",
                pair: "EURUSD",
                direction: "BUY",
                lot_size: 0.05,
                entry_price: 1.1,
                stop_loss: 1.095,
                take_profit: 1.11,
                pnl: -3.2,
                opened_at: "2025-01-01T02:00:00Z",
            },
        ],
        closed: [
            {
                trade_id: "T-CLOSED-001",
                account_id: "ACC-001",
                status: "CLOSED",
                pair: "USDJPY",
                direction: "BUY",
                lot_size: 0.15,
                entry_price: 150.0,
                stop_loss: 149.5,
                take_profit: 151.0,
                pnl: 42.0,
                opened_at: "2025-01-01T00:00:00Z",
                closed_at: "2025-01-01T03:00:00Z",
                close_reason: "TP_HIT",
            },
        ],
        cancelled: [],
    },
    exposure: {
        by_pair: [
            { pair: "EURUSD", total_lots: 0.15, buy_lots: 0.15, sell_lots: 0, count: 2 },
            { pair: "GBPUSD", total_lots: 0.2, buy_lots: 0, sell_lots: 0.2, count: 1 },
        ],
        by_account: [
            { account_id: "ACC-001", total_lots: 0.3, count: 2, pairs: ["EURUSD", "GBPUSD"] },
            { account_id: "ACC-002", total_lots: 0.05, count: 1, pairs: ["EURUSD"] },
        ],
        total_lots: 0.35,
        total_trades: 3,
    },
    anomalies: [
        {
            trade_id: "T-PEND-001",
            anomalies: [
                { type: "STALE_PENDING", message: "Pending > 5 min without fill", severity: "WARNING" },
            ],
        },
    ],
    counts: { pending: 1, open: 2, closed: 1, cancelled: 0, total: 4 },
    server_ts: Date.now() / 1000,
};

const MOCK_DETAIL_RESPONSE = {
    trade: MOCK_DESK_RESPONSE.trades.open[0],
    timeline: [
        { event: "CREATED", status: "INTENDED", timestamp: "2025-01-01T00:50:00Z" },
        { event: "CONFIRMED", status: "PENDING_ACTIVE", timestamp: "2025-01-01T00:55:00Z" },
        { event: "FILLED", status: "OPEN", timestamp: "2025-01-01T01:00:00Z" },
    ],
    anomalies: [],
};

// ── Route interceptors ───────────────────────────────────────

async function mockDeskApi(page: Page) {
    await page.route("**/api/v1/trades/desk**", async (route) => {
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify(MOCK_DESK_RESPONSE),
        });
    });
}

async function mockDetailApi(page: Page) {
    await page.route("**/api/v1/trades/*/detail**", async (route) => {
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify(MOCK_DETAIL_RESPONSE),
        });
    });
}

async function mockConfirmApi(page: Page) {
    await page.route("**/api/v1/trades/*/confirm**", async (route) => {
        if (route.request().method() === "POST") {
            await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({ ok: true }),
            });
        } else {
            await route.continue();
        }
    });
}

async function mockCloseApi(page: Page) {
    await page.route("**/api/v1/trades/*/close**", async (route) => {
        if (route.request().method() === "POST") {
            await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({ ok: true }),
            });
        } else {
            await route.continue();
        }
    });
}

// ══════════════════════════════════════════════════════════════
//  E2E Tests — Trade Desk
// ══════════════════════════════════════════════════════════════

test.describe("Trade Desk", () => {
    test.beforeEach(async ({ page, seedRole }) => {
        await seedRole("trader");
        await mockDeskApi(page);
        await mockDetailApi(page);
        await mockConfirmApi(page);
        await mockCloseApi(page);
    });

    // ── Page renders ─────────────────────────────────────────

    test("opens Trade Desk and shows tabs with counts", async ({ page }) => {
        await page.goto("/trades");
        await expect(page.locator("[data-testid='trade-tab-pending']")).toBeVisible();
        await expect(page.locator("[data-testid='trade-tab-open']")).toBeVisible();
        await expect(page.locator("[data-testid='trade-tab-closed']")).toBeVisible();
        await expect(page.locator("[data-testid='trade-tab-cancelled']")).toBeVisible();

        // Open tab should be active by default
        await expect(page.locator("[data-testid='trade-tab-open']")).toHaveAttribute(
            "data-active",
            "true"
        );
    });

    // ── Trade selection → detail panel ───────────────────────

    test("selecting open trade shows detail panel", async ({ page }) => {
        await page.goto("/trades");

        // Click on the first open trade row
        await page.locator("[data-testid='trade-row-T-OPEN-001']").click();

        // Detail panel should appear with trade info
        await expect(page.locator("[data-testid='trade-detail-panel']")).toBeVisible();
        await expect(page.locator("[data-testid='trade-detail-panel']")).toContainText("T-OPEN-001");
    });

    // ── Detail panel has execution timeline ──────────────────

    test("detail panel shows execution timeline", async ({ page }) => {
        await page.goto("/trades");
        await page.locator("[data-testid='trade-row-T-OPEN-001']").click();

        // Timeline should show events
        await expect(page.locator("[data-testid='execution-timeline']")).toBeVisible();
        await expect(page.locator("[data-testid='execution-timeline']")).toContainText("CREATED");
        await expect(page.locator("[data-testid='execution-timeline']")).toContainText("FILLED");
    });

    // ── Confirm pending trade ────────────────────────────────

    test("confirm pending trade sends POST", async ({ page }) => {
        await page.goto("/trades");

        // Switch to pending tab
        await page.locator("[data-testid='trade-tab-pending']").click();

        // Select pending trade
        await page.locator("[data-testid='trade-row-T-PEND-001']").click();

        // Action panel should show confirm button
        const confirmBtn = page.locator("[data-testid='confirm-trade-btn']");
        await expect(confirmBtn).toBeVisible();

        // Intercept the confirm request
        const requestPromise = page.waitForRequest(
            (req) => req.url().includes("/confirm") && req.method() === "POST"
        );

        await confirmBtn.click();
        const request = await requestPromise;
        expect(request.method()).toBe("POST");
    });

    // ── Close trade ──────────────────────────────────────────

    test("close trade button sends POST", async ({ page }) => {
        await page.goto("/trades");

        // Select an open trade
        await page.locator("[data-testid='trade-row-T-OPEN-001']").click();

        const closeBtn = page.locator("[data-testid='close-trade-btn']");
        await expect(closeBtn).toBeVisible();

        const requestPromise = page.waitForRequest(
            (req) => req.url().includes("/close") && req.method() === "POST"
        );

        await closeBtn.click();
        const request = await requestPromise;
        expect(request.method()).toBe("POST");
    });

    // ── Anomaly banner ───────────────────────────────────────

    test("anomaly banner appears when anomalies exist", async ({ page }) => {
        await page.goto("/trades");

        await expect(page.locator("[data-testid='anomaly-banner']")).toBeVisible();
        await expect(page.locator("[data-testid='anomaly-banner']")).toContainText("anomal");
    });

    // ── Exposure summary ─────────────────────────────────────

    test("exposure summary panel shows pair and account data", async ({ page }) => {
        await page.goto("/trades");

        const exposure = page.locator("[data-testid='exposure-panel']");
        await expect(exposure).toBeVisible();
        await expect(exposure).toContainText("EURUSD");
        await expect(exposure).toContainText("GBPUSD");
        await expect(exposure).toContainText("ACC-001");
    });

    // ── Mismatch indicator ───────────────────────────────────

    test("mismatch state renders when backend sends anomaly flag", async ({ page }) => {
        // Override desk response with mismatch data
        await page.route("**/api/v1/trades/desk**", async (route) => {
            const resp = {
                ...MOCK_DESK_RESPONSE,
                anomalies: [
                    {
                        trade_id: "T-OPEN-001",
                        anomalies: [
                            { type: "EXECUTION_MISMATCH", message: "Lot size mismatch", severity: "CRITICAL" },
                        ],
                    },
                ],
            };
            await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify(resp),
            });
        });

        await page.goto("/trades");

        // Mismatch indicator should be visible on the trade row or banner
        await expect(page.locator("[data-testid='anomaly-banner']")).toBeVisible();
    });
});
