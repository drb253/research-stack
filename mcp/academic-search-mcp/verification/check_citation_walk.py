import sys
sys.path.insert(0, '/Users/drb/.local/share/academic-search-mcp/src')
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
