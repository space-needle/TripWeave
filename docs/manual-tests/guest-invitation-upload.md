# Guest Invitation Upload Manual Test

Use this path after `docker compose -f deploy/compose.local.yml up --build` is running.

1. Open `http://localhost:3000` in a normal browser window.
2. Register or sign in as the trip owner.
3. Create a trip, then open the trip dashboard.
4. In Travelers, create a contributor invitation and copy the invite link.
5. Open the invite link in an incognito or private browser window.
6. Confirm that only the trip title and contributor role are shown before joining.
7. Enter a display name and accept the invitation.
8. Upload one or more JPEG or HEIC images from the contributor page.
9. Refresh the incognito window and confirm the guest session still shows the contributor page and only that guest's uploads.
10. Return to the owner window and confirm the uploaded media appears with the contributor display name.
11. In the owner window, remove the contributor from the member roster.
12. Refresh the incognito window and confirm future access is denied while the owner can still see the existing media attribution.
