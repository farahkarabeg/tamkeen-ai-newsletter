# In-Teams Approve/Reject — Power Automate flow

This adds an **Approve / Reject** button to the digest *inside Teams*. On
Approve, the digest is broadcast to all-staff automatically — no manual Phase B,
no GitHub click.

It uses the **chat-based** approval (reliable in every tenant). The approval
card goes to a **P&S group chat**; the broadcast goes to the **All-Staff
channel**. No bot, no Azure app, no premium connector, no admin involvement
(beyond your tenant already allowing Power Automate, which it does).

```
GitHub Phase A (daily 10:00 GST)
   └─ generates digest, POSTs a bundle to this flow's trigger URL
            │
   Flow ────┼─ Parse JSON
            ├─ Post adaptive card + [Approve] [Reject] to P&S group chat → WAIT
            ├─ Approve → Post the clean card to the All-Staff channel
            └─ Reject  → post "rejected" note, stop
```

---

## What our code sends the flow (the "bundle")

Phase A POSTs this JSON to the flow's trigger URL:

```json
{
  "digestId": "2026-06-17",
  "subtitle": "Wednesday, 17 June 2026",
  "reviewCard":   { "...Adaptive Card with Approve/Reject buttons..." },
  "broadcastCard":{ "...clean Adaptive Card, no draft banner..." }
}
```

- `reviewCard` already contains the two `Action.Submit` buttons. Their submitted
  data is `{"action":"approve"|"reject","digestId":"..."}` — that's how the flow
  knows which branch to take.
- `broadcastCard` is the exact, banner-free card to send on approval. The flow
  holds it between approval and broadcast, so all-staff gets precisely what P&S
  saw.

---

## Build the flow (≈30–45 min, all low-code)

### Prerequisites
- A **P&S group chat** in Teams (or the list of P&S members' emails).
- Membership of the **All-Staff** team/channel you'll broadcast to.

### Steps
1. **Power Automate** (make.powerautomate.com or the Teams "Workflows" app) →
   **Create → Instant cloud flow → Skip** (build blank).

2. **Trigger:** add **"When a Teams webhook request is received."**
   - Set *Who can trigger* to **Anyone** (GitHub posts to it unauthenticated via
     the secret URL).
   - Save once to generate the **HTTP POST URL** — this is your
     `TEAMS_APPROVAL_FLOW_URL`. Copy it.

3. **Parse the payload:** add **"Parse JSON."**
   - *Content:* the trigger's **Body**.
   - *Schema:* paste:
     ```json
     {
       "type": "object",
       "properties": {
         "digestId": { "type": "string" },
         "subtitle": { "type": "string" },
         "reviewCard": { "type": "object" },
         "broadcastCard": { "type": "object" }
       }
     }
     ```

4. **Post & wait:** add Teams **"Post adaptive card and wait for a response."**
   - *Post as:* **Flow bot**.
   - *Post in:* **Group chat** (or **Chat with Flow bot** and add the P&S
     members). Pick/define your P&S group chat.
   - *Adaptive Card:* expression `string(body('Parse_JSON')?['reviewCard'])`
     (the action expects card text; `string(...)` serialises the object).
   - *Update message:* e.g. `Recorded — thank you. (digest @{body('Parse_JSON')?['digestId']})`

5. **Branch on the click:** add a **Condition.**
   - Left: the submitted action. With the "wait for a response" output this is
     typically `body('Post_adaptive_card_and_wait_for_a_response')?['data']?['action']`
     (or use the dynamic-content token named `action`).
   - Operator: **is equal to** → Right: `approve`.

6. **If yes (approved):** add Teams **"Post card in a chat or channel."**
   - *Post in:* **Channel** → choose your **Team** and the **All-Staff** channel.
   - *Adaptive Card:* `string(body('Parse_JSON')?['broadcastCard'])`.

7. **If no (rejected):** optional — Teams **"Post message in a chat or channel"**
   back to the P&S group chat: `Digest @{body('Parse_JSON')?['digestId']} was rejected — not broadcast.`

8. **Save.**

> Tip: test the flow in isolation first — in Power Automate click **Test →
> Manually**, and POST a small sample bundle to the trigger URL (the
> `--dry-run` output below gives you a real one to paste).

---

## Switch AI Pulse to approval-flow mode

1. In `config.yaml` set:
   ```yaml
   deliver:
     mode: "approval_flow"
   ```
2. Add the GitHub secret **`TEAMS_APPROVAL_FLOW_URL`** = the trigger URL from
   step 2 (Settings → Secrets and variables → Actions). In this mode the two
   `TEAMS_*_WEBHOOK_URL` secrets are no longer used.
3. Commit + push. From the next run on, Phase A hands off to the flow.

### Verify before relying on it
- **See the exact bundle** without sending anything:
  ```
  .\.venv\Scripts\python.exe -m ai_pulse --dry-run
  ```
  In approval-flow mode this prints the JSON bundle (paste it into the flow's
  test to validate end-to-end).
- **Real run:** trigger Phase A (locally or via the GitHub workflow). The
  Approve/Reject card lands in the P&S group chat; click **Approve** → the clean
  digest appears in All-Staff.

---

## Notes & trade-offs

- **Manual Phase B is no longer needed** in this mode. (The Phase B workflow
  still exists as a fallback for `direct` mode.)
- **Dedup:** because the flow performs the broadcast, AI Pulse marks a digest's
  stories as "seen" when it hands them off (so a story proposed to P&S is not
  re-proposed the next day, even if rejected). This is usually the right
  behaviour for a daily digest; switch back to `direct` mode if you need
  "record-only-on-broadcast."
- **Channel fallback:** if you later want the approval *in a channel* rather than
  a group chat, swap step 4's target — but channel "wait for a response" is less
  consistent across tenants, which is why this guide uses a group chat.
- **Upgrade path:** true in-card refresh ("✅ Approved by Jane, 10:14") and
  per-person delivery still require the bot + Microsoft Graph route described in
  the main README.
