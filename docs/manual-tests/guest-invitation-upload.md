# Account Invitation Upload Manual Test

Use this path after `docker compose -f deploy/compose.local.yml up --build` is running.

1. Open `http://localhost:3000` in a normal browser window.
2. Register or sign in as the trip owner.
3. Create a trip, then open the trip dashboard.
4. In Travelers, create a contributor invitation and copy the invite link.
5. Open the invite link in an incognito or private browser window.
6. Confirm that only the trip title and contributor role are shown before joining.
7. Create a contributor account or log in with an existing account.
8. Accept the invitation and confirm the trip opens in the authenticated workspace.
9. Upload one or more JPEG or HEIC images.
10. Refresh the incognito window and confirm the signed-in contributor can reopen the trip from the account session.
11. Return to the owner window and confirm the uploaded media appears with the contributor display name.
12. In the owner window, remove the contributor from the member roster.
13. Refresh the incognito window and confirm future access is denied while the owner can still see the existing media attribution.
