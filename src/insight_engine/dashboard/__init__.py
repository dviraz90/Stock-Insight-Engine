"""Dashboard package — read-only presentation of the M0 pipeline's data.

Split into a data layer (`read_model.py`) and a render layer (`render_html.py`)
so a future FastAPI read endpoint (M3) can reuse the data layer untouched.
"""
