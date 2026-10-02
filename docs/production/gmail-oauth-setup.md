# Gmail OAuth setup — owner action

Status: application support is implemented and locally verified. Production remains disabled
until the owner creates the Google OAuth client and completes an explicit consent flow.

## Fixed application values

- Application type: Web application
- Application name: `AI Outreach System`
- OAuth client name: `AI Outreach Production Web`
- Authorized JavaScript origins: none required
- Authorized redirect URI:
  `https://outreach.shaidigroup.com/auth/gmail/callback`
- Scopes:
  - `https://www.googleapis.com/auth/gmail.send`
  - `https://www.googleapis.com/auth/gmail.readonly`

The read-only scope is used only to inspect Gmail thread IDs created by this application. The
worker does not list or search the owner's general inbox. It fetches only known outreach threads.

## Google Cloud Console steps

1. Create or select a dedicated project named `AI Outreach Production`.
2. Open **APIs & Services → Library**, find **Gmail API**, and click **Enable**.
3. Open **Google Auth Platform → Branding** (or **Get started**):
   - App name: `AI Outreach System`;
   - User support email: owner's Gmail address;
   - Developer contact email: owner's Gmail address;
   - do not add a logo for the first private test.
4. Open **Audience**:
   - User type: **External** for a personal Gmail account;
   - Publishing status: **Testing** for the first connection;
   - add the owner's Gmail address as the only test user.
5. Open **Data Access → Add or remove scopes** and add exactly the two scopes listed above.
6. Open **Clients → Create client**:
   - Application type: **Web application**;
   - Name: `AI Outreach Production Web`;
   - leave Authorized JavaScript origins empty;
   - add the exact redirect URI listed above;
   - click **Create**.
7. Save the client ID and client secret outside the repository. Never paste either secret or the
   downloaded JSON into chat. The production configuration flow will collect them locally and
   send them directly to the approved VPS.

## Safety state

- `ALLOW_REAL_EMAIL=false`
- `EMAIL_DELIVERY_PROVIDER=smtp`
- `GMAIL_OAUTH_ENABLED=false`
- `GMAIL_SYNC_ENABLED=false`
- no Gmail refresh token exists
- no email is sent or read during console setup

Testing-mode Gmail grants that include these scopes expire after seven days. After the first
private acceptance test, the owner must choose between publishing the personal-use app as
In production (with Google's unverified-app warning and user cap where applicable) or completing
Google verification. This decision is separate from the initial connection test.
