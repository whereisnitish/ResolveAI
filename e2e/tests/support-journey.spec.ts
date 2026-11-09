import { expect, test, type Page } from "@playwright/test";

/**
 * The core product loop, through real browsers only:
 * signup → knowledge → deploy AI agent → configure widget → visitor chats on a customer
 * site → AI answers → teammate sees it in the inbox and replies → visitor gets the
 * human reply in real time.
 */

const API_URL = process.env.E2E_API_URL ?? "http://localhost:8001";
const WIDGET_URL = process.env.E2E_WIDGET_URL ?? "http://localhost:3002";
const run = Date.now().toString(36);
const owner = {
  name: "Priya Sharma",
  email: `e2e-${run}@example.com`,
  company: `E2E Store ${run}`,
  password: "E2e-Very-Secret-Passw0rd!",
};
// Phrased to overlap the knowledge text: E2E runs with the local lexical embedder.
const VISITOR_QUESTION = "What is your refund policy?";
const HUMAN_REPLY = `A human here — happy to help (${run}).`;

test.describe.configure({ mode: "serial" });

let dashboard: Page;
let widgetWorkspaceId = "";

test.beforeAll(async ({ browser }) => {
  dashboard = await (await browser.newContext()).newPage();
});

test("owner signs up and lands in the app", async () => {
  await dashboard.goto("/signup");
  await dashboard.getByLabel("Your name").fill(owner.name);
  await dashboard.getByLabel("Work email").fill(owner.email);
  await dashboard.getByLabel("Company name").fill(owner.company);
  await dashboard.getByLabel("Password").fill(owner.password);
  await dashboard.getByRole("button", { name: "Create account" }).click();
  await expect(dashboard).toHaveURL(/\/app(\/|$|\?)/);
});

test("owner adds a knowledge source and it gets indexed", async () => {
  await dashboard.goto("/app/knowledge");
  await dashboard.getByRole("button", { name: "Add knowledge" }).click();
  const dialog = dashboard.getByRole("dialog");
  await dialog.getByRole("tab", { name: "Text" }).click();
  await dialog
    .getByPlaceholder(/Paste policies, product details/)
    .fill(
      "Refund policy. Customers can request a full refund within 30 days of purchase. " +
        "Refunds are processed to the original payment method within 5 business days.",
    );
  await dialog.locator("#k-title").fill("Refund policy");
  await dialog.getByRole("button", { name: "Add source" }).click();
  await expect(dialog).toBeHidden();
  const row = dashboard.getByRole("link", { name: /Refund policy/ });
  await expect(async () => {
    await dashboard.reload();
    await expect(row.getByText("Ready")).toBeVisible({ timeout: 2_000 });
  }).toPass({ timeout: 30_000 });
});

test("owner creates an AI agent and deploys it to the widget", async () => {
  await dashboard.goto("/app/ai-agents/new");
  await dashboard.getByPlaceholder("e.g. Ava").fill("Ava");
  await dashboard.getByRole("button", { name: "Create agent" }).click();
  await expect(dashboard).toHaveURL(/\/app\/ai-agents\/[0-9a-f-]{36}/);
  await dashboard.getByRole("button", { name: "Deploy to widget" }).click();
  await expect(dashboard.getByText("Live on widget").first()).toBeVisible();
});

test("owner allows the demo site and reads the widget id", async () => {
  await dashboard.goto("/app/settings?tab=widget");
  await dashboard.locator("#w-origins").fill(WIDGET_URL);
  await dashboard.getByRole("button", { name: "Save changes" }).click();
  await expect(dashboard.getByText("Widget settings saved")).toBeVisible();

  const snippet = dashboard.locator("pre").filter({ hasText: "data-workspace-id" });
  const text = (await snippet.textContent()) ?? "";
  widgetWorkspaceId = /data-workspace-id="(ws_[A-Za-z0-9_-]+)"/.exec(text)?.[1] ?? "";
  expect(widgetWorkspaceId).toMatch(/^ws_/);
});

test("visitor chats on the customer site, AI answers, a teammate takes over", async ({ browser }) => {
  // The visitor is a different browser context: no dashboard cookies, different origin.
  const visitor = await (await browser.newContext()).newPage();
  await visitor.goto(`${WIDGET_URL}/?ws=${widgetWorkspaceId}&api=${encodeURIComponent(API_URL)}`);
  await visitor.getByRole("button", { name: /^Chat with/ }).click();
  const chat = visitor.getByRole("dialog", { name: /^Chat with/ });
  await chat.getByRole("textbox", { name: "Message" }).fill(VISITOR_QUESTION);
  await chat.getByRole("textbox", { name: "Message" }).press("Enter");
  await expect(chat.locator(".row.me .bubble").filter({ hasText: VISITOR_QUESTION })).toBeVisible();

  // The AI agent replies (mock provider in E2E, grounded in the knowledge source).
  const aiReply = chat.locator(".row.them").filter({ has: visitor.locator(".meta", { hasText: "AI assistant" }) });
  await expect(aiReply.first()).toBeVisible({ timeout: 45_000 });

  // A teammate finds the conversation in the inbox.
  await dashboard.goto("/app/inbox?view=all&status=open");
  const row = dashboard.getByRole("link").filter({ hasText: /#\d+/ }).first();
  await expect(row).toBeVisible();
  await row.click();
  const log = dashboard.getByRole("log", { name: "Conversation messages" });
  await expect(log.getByText(VISITOR_QUESTION)).toBeVisible();
  await expect(log.getByText("AI assistant").first()).toBeVisible();
  // The AI answered from knowledge (no handoff) and still owns the conversation.
  await expect(dashboard.getByText(/AI is handling this conversation/)).toBeVisible();
  await expect(dashboard.getByText(/AI handed/)).toHaveCount(0);

  // …and replies; the visitor receives it live over the widget socket.
  const composer = dashboard.getByRole("textbox", { name: "Reply" });
  await composer.fill(HUMAN_REPLY);
  await composer.press("Enter");
  await expect(log.getByText(HUMAN_REPLY)).toBeVisible();
  await expect(chat.locator(".row.them .bubble").filter({ hasText: HUMAN_REPLY })).toBeVisible();

  // A human reply pauses the AI for this conversation.
  await expect(dashboard.getByText(/A teammate took over/)).toBeVisible();
});

test("signed-out users cannot open the dashboard", async ({ browser }) => {
  const anon = await (await browser.newContext()).newPage();
  await anon.goto("/app/inbox");
  await expect(anon).toHaveURL(/\/login\?next=/);
});
