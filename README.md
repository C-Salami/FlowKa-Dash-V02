# Spa Scheduler — Dash + Drag & Drop (20/80 layout)

Left 20%: New booking, Backlog, Workers.  
Right 80%: Large Plotly Gantt.  
Drag & drop between lists (SortableJS). Gantt updates instantly.

## How it works
- JS in `assets/dnd-init.js` initializes SortableJS on every `.dnd-list`.
- On drop, it emits a `CustomEvent('dnd', { itemId, fromId, toId, newIndex })`.
- `dash-extensions` `EventListener` forwards that into a Dash callback to update the `state`.
- Schedule is sequential per worker starting 09:00.

## Deploy (Dash)
Use Render/Heroku/Railway with:
- Build: `pip install -r requirements.txt`
- Start: `gunicorn app:server`

## Deploy (Streamlit tester)
Use Streamlit Community Cloud with `streamlit_app.py` as entry file.
