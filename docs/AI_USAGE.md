# AI Usage

This project was developed with AI assistance (Claude) as a pair programming partner.

## What AI assisted with

- Scaffolding project structure and boilerplate
- Drafting Pydantic models, streamer, and simulator modules
- Dashboard HTML/CSS layout and Plotly.js chart integration
- Writing unit tests for the book engine
- Documentation drafts

## What required human judgment

- Architecture decisions (Quart over Dash, async queues over Celery for the MVP, Docker as optional layer)
- Domain modelling: how PnL calculation, mark-to-market, and book positions work
- Evaluation trade-offs: prioritising reproducibility and stability over feature count
- Code review, debugging, and integration across components
- Scalability analysis and throttling strategy
