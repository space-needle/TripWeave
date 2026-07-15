import { expect, request, test } from "@playwright/test";

const apiBase = process.env.TRIPWEAVE_LOCAL_API ?? "http://localhost:8000";
const webBase = process.env.TRIPWEAVE_LOCAL_WEB ?? "http://localhost:3000";
const jpegFixture =
  "/9j/4AAQSkZJRgABAQAAAQABAAD/4QEiRXhpZgAATU0AKgAAAAgABwEPAAIAAAANAAAAYgEQAAIAAAAERTJFAAEyAAIAAAAUAAAAcIglAAQAAAABAAAAhJADAAIAAAAUAAAA6pAEAAIAAAAUAAAA/pARAAIAAAAHAAABEgAAAABUcmlwV2VhdmVDYW0AADIwMjY6MDY6MDYgMTA6MDA6MDAAAAQAAQACAAAAAk4AAAAAAgAFAAAAAwAAALoAAwACAAAAAkUAAAAABAAFAAAAAwAAANIAAAAAAAAAIwAAAAEAAAAoAAAAAQAAAAAAAAABAAAAiwAAAAEAAAAtAAAAAQAAAAAAAAABMjAyNjowNjowNiAxMDowMDowMAAyMDI2OjA2OjA2IDEwOjAwOjAwACswOTowMAAA/9sAQwAIBgYHBgUIBwcHCQkICgwUDQwLCwwZEhMPFB0aHx4dGhwcICQuJyAiLCMcHCg3KSwwMTQ0NB8nOT04MjwuMzQy/9sAQwEJCQkMCwwYDQ0YMiEcITIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy/8AAEQgAPABQAwEiAAIRAQMRAf/EAB8AAAEFAQEBAQEBAAAAAAAAAAABAgMEBQYHCAkKC//EALUQAAIBAwMCBAMFBQQEAAABfQECAwAEEQUSITFBBhNRYQcicRQygZGhCCNCscEVUtHwJDNicoIJChYXGBkaJSYnKCkqNDU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6g4SFhoeIiYqSk5SVlpeYmZqio6Slpqeoqaqys7S1tre4ubrCw8TFxsfIycrS09TV1tfY2drh4uPk5ebn6Onq8fLz9PX29/j5+v/EAB8BAAMBAQEBAQEBAQEAAAAAAAABAgMEBQYHCAkKC//EALURAAIBAgQEAwQHBQQEAAECdwABAgMRBAUhMQYSQVEHYXETIjKBCBRCkaGxwQkjM1LwFWJy0QoWJDThJfEXGBkaJicoKSo1Njc4OTpDREVGR0hJSlNUVVZXWFlaY2RlZmdoaWpzdHV2d3h5eoKDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uLj5OXm5+jp6vLz9PX29/j5+v/aAAwDAQACEQMRAD8A4uiiivmT9xCiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigD/9k=";

async function registerOwner() {
  const context = await request.newContext({ baseURL: apiBase });
  const email = `e2e-${Date.now()}@tripweave.local`;
  const response = await context.post("/auth/register", {
    data: {
      email,
      password: "local-e2e-password",
      displayName: "E2E Owner",
    },
  });
  expect(response.status()).toBe(201);
  const body = await response.json();
  return { context, csrf: body.csrfToken as string };
}

async function acceptInvite(inviteUrl: string, displayName: string) {
  const context = await request.newContext({ baseURL: apiBase });
  const token = inviteUrl.split("/").at(-1);
  const response = await context.post(`/invitations/${token}/accept`, {
    data: { displayName },
  });
  expect(response.status()).toBe(200);
  const body = await response.json();
  return { context, csrf: body.csrfToken as string };
}

async function uploadPhoto(
  context: Awaited<ReturnType<typeof request.newContext>>,
  csrf: string,
  tripId: string,
  filename: string,
) {
  const payload = Buffer.from(jpegFixture, "base64");
  const created = await context.post(`/trips/${tripId}/upload-sessions`, {
    headers: { "x-csrf-token": csrf },
    data: {
      files: [{ filename, byteSize: payload.length, mimeType: "image/jpeg" }],
    },
  });
  expect(created.status()).toBe(201);
  const uploadFile = (await created.json()).files[0];
  const grantUrl = new URL(uploadFile.grant.url);
  const put = await context.put(grantUrl.pathname, {
    headers: uploadFile.grant.headers,
    data: payload,
  });
  expect(put.status()).toBe(200);
  const completed = await context.post(
    `/upload-files/${uploadFile.id}/complete`,
    {
      headers: { "x-csrf-token": csrf },
    },
  );
  expect(completed.status()).toBe(200);
}

async function waitForReadyMedia(
  context: Awaited<ReturnType<typeof request.newContext>>,
  tripId: string,
  readyCount: number,
) {
  await expect
    .poll(
      async () => {
        const response = await context.get(`/trips/${tripId}/media`);
        expect(response.status()).toBe(200);
        const body = await response.json();
        return body.media.filter(
          (item: { processingState: string }) =>
            item.processingState === "ready",
        ).length;
      },
      { timeout: 90_000 },
    )
    .toBeGreaterThanOrEqual(readyCount);
}

test("local MVP publication path", async ({ page }) => {
  const owner = await registerOwner();
  const tripResponse = await owner.context.post("/trips", {
    headers: { "x-csrf-token": owner.csrf },
    data: {
      title: "Playwright Local MVP",
      timezoneId: "Asia/Tokyo",
      dayCutoffHour: 4,
    },
  });
  expect(tripResponse.status()).toBe(201);
  const trip = await tripResponse.json();

  const inviteOne = await owner.context.post(`/trips/${trip.id}/invitations`, {
    headers: { "x-csrf-token": owner.csrf },
    data: {},
  });
  expect(inviteOne.status()).toBe(201);
  const inviteTwo = await owner.context.post(`/trips/${trip.id}/invitations`, {
    headers: { "x-csrf-token": owner.csrf },
    data: {},
  });
  expect(inviteTwo.status()).toBe(201);

  const guestOne = await acceptInvite(
    (await inviteOne.json()).inviteUrl,
    "Guest One",
  );
  const guestTwo = await acceptInvite(
    (await inviteTwo.json()).inviteUrl,
    "Guest Two",
  );

  await uploadPhoto(owner.context, owner.csrf, trip.id, "owner.jpg");
  await uploadPhoto(guestOne.context, guestOne.csrf, trip.id, "guest-one.jpg");
  await uploadPhoto(guestTwo.context, guestTwo.csrf, trip.id, "guest-two.jpg");
  await waitForReadyMedia(owner.context, trip.id, 3);

  const reconstructed = await owner.context.post(
    `/trips/${trip.id}/reconstruction-runs`,
    {
      headers: { "x-csrf-token": owner.csrf },
    },
  );
  expect(reconstructed.status()).toBe(200);
  expect((await reconstructed.json()).days.length).toBeGreaterThan(0);

  const publication = await owner.context.post(
    `/trips/${trip.id}/publications`,
    {
      headers: { "x-csrf-token": owner.csrf },
    },
  );
  expect(publication.status()).toBe(200);
  const shareUrl = (await publication.json()).shareLink.shareUrl as string;

  await expect
    .poll(
      async () => {
        const response = await owner.context.get(
          `/public/shares/${shareUrl.split("/").at(-1)}`,
        );
        return response.status();
      },
      { timeout: 90_000 },
    )
    .toBe(200);

  const storyUrl = shareUrl.replace("http://localhost:3000", webBase);
  await page.goto(storyUrl);
  await expect(
    page.getByRole("heading", { name: "Playwright Local MVP" }),
  ).toBeVisible();
  const travelerFilter = page.getByLabel("Traveler");
  await travelerFilter.selectOption({ label: "Guest One" });
  await expect(travelerFilter).not.toHaveValue("everyone");

  const links = await owner.context.get(`/trips/${trip.id}/publications`);
  const activeLink = (await links.json()).shareLinks[0];
  const revoked = await owner.context.delete(`/share-links/${activeLink.id}`, {
    headers: { "x-csrf-token": owner.csrf },
  });
  expect(revoked.status()).toBe(204);

  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Story unavailable" }),
  ).toBeVisible();
});
