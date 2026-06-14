"""Diagnostic script to trace meta test failures."""
import sys, math, traceback, csv, io
sys.path.insert(0, 'F:/Projects/psyclaw')
from psyclaw.psych.meta import compute_meta, format_apa, _parse_csv, _fisher_z

# test_format_apa_p_lt001
print("=== test_format_apa_p_lt001 ===")
try:
    studies = [{'label': f'S{i+1}', 'd': 5.0, 'se': 0.01} for i in range(4)]
    r = compute_meta(studies)
    print('compute_meta ok')
    txt = format_apa(r)
    print('format_apa ok:', txt[:60])
except Exception as e:
    traceback.print_exc()

# test_egger_present_k10
print("\n=== test_egger_present_k10 ===")
try:
    studies = [{'label': f'S{i+1}', 'd': 0.2 + i * 0.05, 'se': 0.1 + i * 0.01} for i in range(10)]
    r = compute_meta(studies)
    print('compute_meta ok, egger keys:', list(r['egger'].keys()))
except Exception as e:
    traceback.print_exc()

# test_parse_csv_r_type
print("\n=== test_parse_csv_r_type ===")
try:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['study', 'r', 'n'])
    w.writerow(['S1', 0.4, 100])
    w.writerow(['S2', 0.5, 120])
    txt = buf.getvalue()
    eff_type, studies = _parse_csv(txt)
    print('ok, eff_type=', eff_type, 'studies[0][d]=', studies[0]['d'])
except Exception as e:
    traceback.print_exc()

# test_tau_eq_sqrt_tau2 (empty error)
print("\n=== test_tau_eq_sqrt_tau2 ===")
try:
    studies = [{'label': f'S{i+1}', 'd': d, 'se': s} for i, (d, s) in enumerate(zip([0.1, 0.9], [0.05, 0.05]))]
    r = compute_meta(studies)
    h = r['heterogeneity']
    print(f'tau={h["tau"]}, sqrt(tau2)={math.sqrt(h["tau2"])}')
    assert abs(h['tau'] - math.sqrt(h['tau2'])) < 1e-6, f"FAIL: diff={abs(h['tau'] - math.sqrt(h['tau2']))}"
    print('ok')
except Exception as e:
    traceback.print_exc()
