"""LandAuction core: database models, geometry helpers and auction business rules.

This package has no Streamlit dependency (apart from optionally reading
``st.secrets`` in :mod:`landauction.config`), so the rules can be unit-tested
and reused behind another UI or API later.
"""

__version__ = "2.0.0"
