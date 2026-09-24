# omnideck app 0.4.0

## Added

- **Chat:** Unsent text typed into a conversation's message box is now saved to this browser and restored on reload, navigating away and back, or reopening the app — scoped to that one conversation.
- **Customization:** A blank `custom.css` is now created automatically and loaded after core styles, so you can drop in your own CSS overrides without editing core files or losing them on update.

## Changed

- **UI:** Refreshed the visual design of the chat, sidebar, and composer: a friendlier self-hosted Inter typeface throughout (replacing the monospace brand font), softer rounded corners, and a lighter sidebar. The chat's empty-state heading and cards are bigger and better balanced, the sidebar's active section is easier to read, and the composer's send button is now an up arrow. The composer's full-screen expand now grows to about 80% of the window's height while keeping its normal width and floating over the conversation, instead of taking over the whole panel.

## Fixed

- **Integrations:** The Google Drive integration now sees files and folders in Shared Drives, and items shared by other users, instead of only the connected account's own My Drive.
