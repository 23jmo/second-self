import { Auth0Client } from "@auth0/nextjs-auth0/server";

export const auth0 = new Auth0Client({
  authorizationParameters: {
    scope: "openid profile email",
    // Google API scopes requested via Auth0 social connection
    connection_scope:
      "https://www.googleapis.com/auth/gmail.readonly " +
      "https://www.googleapis.com/auth/gmail.send " +
      "https://www.googleapis.com/auth/calendar.readonly " +
      "https://www.googleapis.com/auth/calendar.events " +
      "https://www.googleapis.com/auth/documents " +
      "https://www.googleapis.com/auth/presentations " +
      "https://www.googleapis.com/auth/drive.file",
  },
});
