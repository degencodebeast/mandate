# Mandate calls Circle CLI via subprocess, not REST API or MCP client

The Mandate Service calls the Circle CLI via subprocess to execute wallets, nanopayments, and service discovery. The CLI is already built and tested by Circle. We rejected calling Circle REST APIs directly (more code to write and maintain, reimplementing what the CLI does) and connecting to the Circle MCP server as a client (would require the agent to connect to two MCP servers, adding complexity).

**Note:** The CLI is a Node.js tool (`@circle-fin/cli`). It is called from Python via `subprocess.run()`. The output is parsed as JSON. This is a pragmatic choice for a production product: the CLI handles auth, wallet creation, signing, and settlement. We do not reimplement those.
