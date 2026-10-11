import os
import sys

# Portable: resolve the package from this checkout (override with ACADEMIC_SEARCH_SRC).
_SRC = os.environ.get("ACADEMIC_SEARCH_SRC") or os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "src")
)
sys.path.insert(0, _SRC)
from academic_search import server
f = lambda n: getattr(getattr(server, n), 'fn', getattr(server, n))
try:
    r = f('explore_citations')('DOI:10.1038/s41586-020-2649-2', num_steps=1, max_depth=1, direction_choice='forward')
    print('SEED:', r['seed_paper_id'])
    print('STATS:', r['stats'])
    print('EDGES:', len(r['edges']), 'PATH:', len(r['path']))
    print('DIAGNOSTICS:', r.get('diagnostics'))
except Exception as e:
    print('FAILED:', type(e).__name__, str(e)[:280])
